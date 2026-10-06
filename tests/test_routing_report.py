import json
import os
from types import SimpleNamespace

from src.config import EVAL_QUESTIONS_PATH, ROUTING_PROBE_PATH, SEED_DATA_DIR
from src.evaluation import routing_report
from src.evaluation.evaluator import load_questions
from src.routing.classifier import GENERAL_KNOWLEDGE_DATA, NON_RETRIEVAL_DATA
from src.routing.router import RouteResult


def test_benchmark_sources_name_real_seed_files():
    """Verify every benchmark source_doc is 'general' or a file in data/: the routing checks compare it to real sources."""
    seed_files = set(os.listdir(SEED_DATA_DIR))
    for q in load_questions(EVAL_QUESTIONS_PATH):
        assert q["source_doc"] == "general" or q["source_doc"] in seed_files, q["source_doc"]


def test_probe_fixture_expectations_and_no_overlap_with_training():
    """Verify every group but off_corpus and near_topic names a batch source, and off-corpus questions expect no retrieval and are never training negatives."""
    with open(ROUTING_PROBE_PATH, "r", encoding="utf-8") as f:
        probe = json.load(f)
    for group, questions in probe.items():
        if group in ("off_corpus", "near_topic"):
            assert all("source_doc" not in q for q in questions), group
        else:
            assert all(q["source_doc"].startswith("ingested/batch/") for q in questions), group
    negatives = {text.lower() for text, _ in NON_RETRIEVAL_DATA + GENERAL_KNOWLEDGE_DATA}
    assert not negatives & {q["query"].lower() for q in probe["off_corpus"] + probe["near_topic"]}


def test_general_benchmark_question_expects_no_retrieval(tmp_path):
    """Verify 'general' benchmark questions and fixture questions without a source expect no retrieval."""
    questions, probe = tmp_path / "questions.json", tmp_path / "probe.json"
    questions.write_text(json.dumps([{"query": "2 + 2?", "source_doc": "general"},
                                     {"query": "Cats?", "source_doc": "cat-facts.txt"}]), encoding="utf-8")
    probe.write_text(json.dumps({"off_corpus": [{"query": "Capital of Peru?"}]}), encoding="utf-8")

    assert routing_report.load_probe_questions(str(questions), str(probe)) == [
        ("benchmark", "2 + 2?", None), ("benchmark", "Cats?", "cat-facts.txt"), ("off_corpus", "Capital of Peru?", None),
    ]


def test_rows_are_scored_against_their_expectation(monkeypatch):
    """Verify right source, wrong source and wrong retrieval are each scored and counted correctly."""
    routes = {
        "Cats?": RouteResult(True, "cat-facts.txt", 0.61, None, "classifier"),
        "Quokkas?": RouteResult(True, "cat-facts.txt", 0.54, 0.70, "probe"),
        "Capital of Peru?": RouteResult(True, "fictional_text.txt", 0.40, 0.60, "probe"),
        "Hello!": RouteResult(False, "none", 0.80, 0.20, "no_retrieval"),
    }
    monkeypatch.setattr(routing_report, "decide_route", lambda emb, vs, query: routes[emb])
    vectorstore = SimpleNamespace(_embedding_function=SimpleNamespace(embed_query=lambda text: text))
    items = [("benchmark", "Cats?", "cat-facts.txt"), ("new_docs", "Quokkas?", "ingested/batch/quokkas.md"),
             ("off_corpus", "Capital of Peru?", None), ("off_corpus", "Hello!", None)]

    rows = routing_report.run_routing_report(vectorstore, items)

    assert [row.ok for row in rows] == [True, False, False, True]
    summary = routing_report.summarize(rows)
    assert summary["new_docs"] == {"questions": 1, "classifier_yes": 0, "probe_overruled": 1, "expect_retrieval": 1,
                                   "reached": 1, "right_source": 0, "expect_none": 0, "wrongly_retrieved": 0}
    assert (summary["off_corpus"]["expect_none"], summary["off_corpus"]["wrongly_retrieved"]) == (2, 1)
    assert "[expected ingested/batch/quokkas.md]" in routing_report.format_report(rows)


def test_benchmark_routing_failures_lists_only_the_misrouted_questions(tmp_path, monkeypatch):
    """Verify the publish guard reports a question routed to the wrong source and a general question that retrieves."""
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps([{"query": "Cats?", "source_doc": "cat-facts.txt"},
                                     {"query": "Oakhaven?", "source_doc": "fictional_text.txt"},
                                     {"query": "2 + 2?", "source_doc": "general"}]), encoding="utf-8")
    routes = {
        "Cats?": RouteResult(True, "cat-facts.txt", 0.61, 0.70, "classifier"),
        "Oakhaven?": RouteResult(True, "ingested/batch/clowder.md", 0.58, 0.66, "classifier"),
        "2 + 2?": RouteResult(True, "pydantic.llms-full.txt", 0.40, 0.58, "probe"),
    }
    monkeypatch.setattr(routing_report, "decide_route", lambda emb, vs, query: routes[emb])
    vectorstore = SimpleNamespace(_embedding_function=SimpleNamespace(embed_query=lambda text: text))

    assert routing_report.benchmark_routing_failures(vectorstore, str(questions)) == [
        "'Oakhaven?': expected fictional_text.txt, routed to ingested/batch/clowder.md (classifier)",
        "'2 + 2?': expected no retrieval, routed to pydantic.llms-full.txt (probe)",
    ]
