from fastapi.testclient import TestClient
from starlette.routing import Mount

from src.core import api
from src.core.rag_agent import AnswerResult, Passage
from src.core.utils import EmptyAnswerError


def raising(error):
    """A stand-in for answer_question that fails with error."""
    def fail(*args, **kwargs):
        raise error
    return fail


def test_mcp_root_mount_is_last_route():
    """Verify the catch-all MCP mount comes after every API route."""
    last = api.app.routes[-1]
    assert isinstance(last, Mount)
    assert last.path == ""


def test_api_routes_stay_reachable_with_root_mount():
    """Verify /health is served by FastAPI, not swallowed by the MCP mount (no lifespan needed)."""
    client = TestClient(api.app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_query_returns_the_answer_with_its_route_and_passages(monkeypatch):
    """Verify /query returns the whole AnswerResult, passages included (no lifespan: answer_question is faked)."""
    result = AnswerResult(answer="A clowder.", source="cat-facts.txt", route_reason="classifier",
                          router_confidence=0.9, probe_similarity=0.62, groundedness_score=0.71,
                          passages=[Passage("cat-facts.txt", "A group of cats is called a clowder.", 0.71)])
    monkeypatch.setattr(api, "answer_question", lambda question, router, vectorstore, llm, **kwargs: result)

    response = TestClient(api.app).post("/query", json={"question": "What is a group of cats called?"})

    assert response.status_code == 200
    assert response.json() == {
        "question": "What is a group of cats called?", "answer": "A clowder.", "source": "cat-facts.txt",
        "route_reason": "classifier", "router_confidence": 0.9, "probe_similarity": 0.62,
        "groundedness_score": 0.71, "cache_hit": False,
        "passages": [{"source": "cat-facts.txt", "text": "A group of cats is called a clowder.", "similarity": 0.71}],
    }


def test_query_records_its_routing_decision_without_the_question(monkeypatch, fake_event_store):
    """Verify each answered /query stores one routing event, marks live-eval's requests and never stores the question."""
    monkeypatch.setattr(api, "event_store", fake_event_store)
    monkeypatch.setattr(api, "APP_REVISION", "abc1234")
    monkeypatch.setattr(api, "answer_question", lambda question, router, vectorstore, llm, **kwargs: AnswerResult(
        answer="A clowder.", source="cat-facts.txt", route_reason="classifier", router_confidence=0.9,
        probe_similarity=0.62, groundedness_score=0.71))
    client = TestClient(api.app)

    client.post("/query", json={"question": "What is a group of cats called?"})
    client.post("/query", json={"question": "What is a group of cats called?"}, headers={"X-RAG-Client": "live-eval"})

    assert [kind for kind, _ in fake_event_store.records] == ["routing", "routing"]
    assert [record["origin"] for _, record in fake_event_store.records] == ["user", "live-eval"]
    assert fake_event_store.records[0][1] == {
        "source": "cat-facts.txt", "route_reason": "classifier", "router_confidence": 0.9, "probe_similarity": 0.62,
        "groundedness_score": 0.71, "cache_hit": False, "origin": "user", "revision": "abc1234",
    }


def test_a_failing_event_store_does_not_fail_the_query(monkeypatch, fake_event_store):
    """Verify the answer still arrives when the routing event can't be stored."""
    fake_event_store.fail = True
    monkeypatch.setattr(api, "event_store", fake_event_store)
    monkeypatch.setattr(api, "answer_question", lambda question, router, vectorstore, llm, **kwargs: AnswerResult(answer="A clowder."))

    response = TestClient(api.app).post("/query", json={"question": "What is a group of cats called?"})

    assert response.status_code == 200
    assert response.json()["answer"] == "A clowder."


def test_live_eval_requests_skip_the_semantic_cache(monkeypatch):
    """Verify users' questions use the semantic cache and live-eval's don't."""
    use_cache = []
    monkeypatch.setattr(api, "answer_question", lambda question, router, vectorstore, llm, **kwargs:
                        use_cache.append(kwargs["use_cache"]) or AnswerResult(answer="A clowder."))
    client = TestClient(api.app)

    client.post("/query", json={"question": "What is a group of cats called?"})
    client.post("/query", json={"question": "What is a group of cats called?"}, headers={"X-RAG-Client": "live-eval"})

    assert use_cache == [True, False]


def test_a_rate_limit_answers_503_with_retry_after(monkeypatch, fake_event_store, rate_limit_error):
    """Verify a rate limit that outlasted the SDK's retries becomes 503 with the wait in Retry-After, and no routing event."""
    monkeypatch.setattr(api, "event_store", fake_event_store)
    monkeypatch.setattr(api, "answer_question", raising(rate_limit_error))

    response = TestClient(api.app).post("/query", json={"question": "What is a group of cats called?"})

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "7"
    assert "try again in 7 s" in response.json()["detail"]
    assert fake_event_store.records == []


def test_a_twice_empty_answer_answers_502(monkeypatch):
    """Verify an answer that stayed blank after the retry becomes 502, not 200 with empty text."""
    monkeypatch.setattr(api, "answer_question", raising(EmptyAnswerError("The LLM returned an empty answer twice")))

    response = TestClient(api.app).post("/query", json={"question": "Who is Elena Rostova?"})

    assert response.status_code == 502


def test_other_errors_still_answer_500(monkeypatch):
    """Verify any other failure keeps today's 500 and detail."""
    monkeypatch.setattr(api, "answer_question", raising(RuntimeError("boom")))

    response = TestClient(api.app).post("/query", json={"question": "What is a group of cats called?"})

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error processing query"


def test_health_reports_the_deployed_revision(monkeypatch):
    """Verify /health shows the git SHA deploy.yml sets, and null locally."""
    monkeypatch.setattr(api, "APP_REVISION", "abc1234")
    assert TestClient(api.app).get("/health").json()["revision"] == "abc1234"
    monkeypatch.setattr(api, "APP_REVISION", "")
    assert TestClient(api.app).get("/health").json()["revision"] is None
