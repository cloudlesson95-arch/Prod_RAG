import json

import pytest
from unittest.mock import patch, MagicMock

from src.evaluation import live_evaluator
from src.evaluation.live_evaluator import run_live_evaluation
from src.evaluation.eval_db import get_eval_history, save_eval_run


@pytest.fixture(autouse=True)
def stored_events(monkeypatch, fake_event_store):
    """Every run here goes to an in-memory event store, never to the real LOCAL_DIR/events."""
    monkeypatch.setattr(live_evaluator, "get_event_store", lambda: fake_event_store)
    return fake_event_store


def test_live_evaluation_with_mocked_http_and_judge(tmp_path):
    db_path = str(tmp_path / "test_eval.db")

    mock_questions = [
        {"id": 1, "query": "What is a group of cats called?", "expected_answer": "A clowder."},
    ]

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"answer": "A group of cats is called a clowder."}

    with patch("src.evaluation.live_evaluator.load_questions", return_value=mock_questions), \
         patch("src.evaluation.live_evaluator.judge_answer", return_value=True), \
         patch("requests.post", return_value=mock_response), \
         patch("src.evaluation.live_evaluator.DB_PATH", db_path):

        run_id, precision, passed = run_live_evaluation("http://localhost:8000", revision="v1.0.0")

        assert run_id > 0
        assert precision == 100.0
        assert passed is True

        history = get_eval_history(db_path, limit=1)
        assert len(history) == 1
        assert history[0]["run_type"] == "live"
        assert history[0]["revision"] == "v1.0.0"


def test_synthetic_run_reads_its_own_file_and_is_saved_as_synthetic(tmp_path):
    """Verify --questions asks the file's questions and stores the run as synthetic, whatever the score."""
    db_path = str(tmp_path / "test_eval.db")
    questions_file = tmp_path / "generated.json"
    questions_file.write_text(json.dumps([{
        "id": 1, "source_doc": "ingested/batch/quokkas.md", "query": "What is the conservation status of the quokka?",
        "expected_context": "The quokka is listed as Vulnerable...", "expected_answer": "Vulnerable on the IUCN Red List.",
        "is_adversarial": False,
    }]), encoding="utf-8")
    mock_response = MagicMock()
    mock_response.json.return_value = {"answer": "I don't know."}

    with patch("src.evaluation.live_evaluator.create_llm", return_value=MagicMock()), \
         patch("src.evaluation.live_evaluator.judge_answer", return_value=False), \
         patch("requests.post", return_value=mock_response) as post, \
         patch("src.evaluation.live_evaluator.DB_PATH", db_path):
        run_id, precision, passed = run_live_evaluation("http://localhost:8000", revision="collect-1",
                                                        questions_path=str(questions_file), run_type="synthetic")

    assert post.call_args.kwargs["json"] == {"question": "What is the conservation status of the quokka?"}
    assert (precision, passed) == (0.0, False)
    assert get_eval_history(db_path, limit=1)[0]["run_type"] == "synthetic"


def test_synthetic_questions_use_the_benchmark_format_and_filter_by_source(monkeypatch):
    """Verify stored questions become benchmark-shaped entries, optionally limited to the given documents."""
    stored = [{"source": "ingested/batch/quokkas.md", "question": "Q1?", "answer": "A1", "context": "C1"},
              {"source": "cat-facts.txt", "question": "Q2?", "answer": "A2", "context": "C2"}]
    monkeypatch.setattr(live_evaluator, "get_current_questions", lambda: stored)

    assert live_evaluator.synthetic_questions(["ingested/batch/quokkas.md"]) == [
        {"id": 1, "source_doc": "ingested/batch/quokkas.md", "query": "Q1?", "expected_context": "C1",
         "expected_answer": "A1", "is_adversarial": False}
    ]
    assert len(live_evaluator.synthetic_questions()) == 2


ONE_QUESTION = {"id": 1, "query": "What is a group of cats called?", "expected_answer": "A clowder."}


def run_once(tmp_path):
    """One benchmark question, answered and judged correct, against a fake deployment."""
    response = MagicMock()
    response.json.return_value = {"answer": "A clowder."}
    with patch("src.evaluation.live_evaluator.load_questions", return_value=[ONE_QUESTION]), \
         patch("src.evaluation.live_evaluator.create_llm", return_value=MagicMock()), \
         patch("src.evaluation.live_evaluator.judge_answer", return_value=True), \
         patch("requests.post", return_value=response) as post, \
         patch("src.evaluation.live_evaluator.DB_PATH", str(tmp_path / "eval.db")):
        return run_live_evaluation("https://app.example.io", revision="abc1234"), post


def test_run_is_stored_as_an_eval_run_event_and_marks_its_requests(tmp_path, stored_events):
    """Verify live-eval marks its /query requests and stores the run, answers included, for the dashboard."""
    _, post = run_once(tmp_path)

    assert post.call_args.kwargs["headers"] == {"X-RAG-Client": "live-eval"}
    [(kind, record)] = stored_events.records
    assert kind == "eval_run"
    assert {key: record[key] for key in ("run_type", "revision", "target_url", "precision_score", "passed_threshold")} == {
        "run_type": "live", "revision": "abc1234", "target_url": "https://app.example.io",
        "precision_score": 100.0, "passed_threshold": True}
    assert record["results"] == [{"id": 1, "query": "What is a group of cats called?", "passed": True,
                                  "llm_answer": "A clowder."}]


def test_a_failing_event_store_does_not_change_the_result(tmp_path, stored_events):
    """Verify the gate's result doesn't depend on the dashboard's storage."""
    stored_events.fail = True

    (run_id, precision, passed), _ = run_once(tmp_path)

    assert (precision, passed) == (100.0, True)
    assert stored_events.records == []
