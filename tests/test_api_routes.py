from fastapi.testclient import TestClient
from starlette.routing import Mount

from src.core import api
from src.core.rag_agent import AnswerResult, Passage


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
    monkeypatch.setattr(api, "answer_question", lambda question, router, vectorstore, llm: result)

    response = TestClient(api.app).post("/query", json={"question": "What is a group of cats called?"})

    assert response.status_code == 200
    assert response.json() == {
        "question": "What is a group of cats called?", "answer": "A clowder.", "source": "cat-facts.txt",
        "route_reason": "classifier", "router_confidence": 0.9, "probe_similarity": 0.62,
        "groundedness_score": 0.71, "cache_hit": False,
        "passages": [{"source": "cat-facts.txt", "text": "A group of cats is called a clowder.", "similarity": 0.71}],
    }
