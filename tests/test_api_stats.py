import pytest
from fastapi.testclient import TestClient

from src.core import api


@pytest.fixture
def client(monkeypatch, fake_event_store):
    """API client with an in-memory event store, a fixed training mix and an empty stats cache (no lifespan)."""
    monkeypatch.setattr(api, "event_store", fake_event_store)
    monkeypatch.setattr(api, "training_source_mix", lambda: {"cat-facts.txt": 5, "none": 5})
    monkeypatch.setattr(api, "_stats_cache", {})
    return TestClient(api.app)


def test_eval_history_returns_stored_runs_newest_first(client, fake_event_store):
    fake_event_store.put("eval_run", {"run_type": "live", "precision_score": 90.0})
    fake_event_store.put("eval_run", {"run_type": "synthetic", "precision_score": 40.0})

    runs = client.get("/stats/eval-history").json()["runs"]

    assert [run["run_type"] for run in runs] == ["synthetic", "live"]


def test_routing_summarizes_stored_events_against_the_training_mix(client, fake_event_store):
    fake_event_store.put("routing", {"source": "cat-facts.txt", "route_reason": "classifier", "cache_hit": False,
                                     "origin": "user", "groundedness_score": 0.7})
    fake_event_store.put("routing", {"source": "cat-facts.txt", "route_reason": "classifier", "cache_hit": False,
                                     "origin": "live-eval", "groundedness_score": 0.6})

    body = client.get("/stats/routing?days=7").json()

    assert (body["queries"], body["live_eval_queries"], body["by_source"]) == (1, 1, {"cat-facts.txt": 1})
    assert body["baseline"] == {"cat-facts.txt": 5, "none": 5}
    assert body["psi"] is None


def test_corpus_lists_documents_with_their_generated_questions(client, monkeypatch):
    monkeypatch.setattr(api, "get_registered_documents", lambda: {"cat-facts.txt": {
        "file_hash": "h", "chunk_count": 12, "file_size": 5000, "ingested_at": "2026-10-01T00:00:00+00:00"}})
    monkeypatch.setattr(api, "get_current_questions", lambda: [{"source": "cat-facts.txt"}] * 5)
    monkeypatch.setattr(api, "read_local_version", lambda: "0xETAG")

    assert client.get("/stats/corpus").json() == {"state_version": "0xETAG", "total_chunks": 12, "documents": [
        {"filename": "cat-facts.txt", "chunk_count": 12, "file_size": 5000,
         "ingested_at": "2026-10-01T00:00:00+00:00", "questions": 5}]}


def test_stats_are_reused_within_the_cache_time(client, fake_event_store):
    """Verify a second request within STATS_CACHE_SECONDS doesn't read the store again."""
    first = client.get("/stats/eval-history").json()
    fake_event_store.put("eval_run", {"run_type": "live"})

    assert client.get("/stats/eval-history").json() == first


def test_an_unreachable_store_answers_503_with_cors_headers(client, fake_event_store):
    """Verify a storage failure reaches the browser as a readable 503, not an opaque network error."""
    fake_event_store.fail = True

    response = client.get("/stats/routing", headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 503
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_out_of_range_parameters_are_rejected(client):
    assert client.get("/stats/routing?days=31").status_code == 422
    assert client.get("/stats/eval-history?limit=0").status_code == 422
