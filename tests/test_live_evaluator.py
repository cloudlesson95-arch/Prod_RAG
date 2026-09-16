import pytest
from unittest.mock import patch, MagicMock

from src.evaluation.live_evaluator import run_live_evaluation
from src.evaluation.eval_db import get_eval_history, save_eval_run


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
