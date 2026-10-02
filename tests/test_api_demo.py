import pytest
from fastapi.testclient import TestClient
from langchain_core.embeddings import DeterministicFakeEmbedding

from src.config import DEMO_TTL_SECONDS
from src.core import api
from src.core.rate_limit import RateLimiter
from src.ingestion.demo import DemoStore

NOTE = ("notes.txt", b"Quokkas live on Rottnest Island.", "text/plain")


@pytest.fixture
def client(monkeypatch):
    """API client with a fake-embedding demo store and a fake answerer; no lifespan, so no models load."""
    monkeypatch.setattr(api, "demo_store", DemoStore(DeterministicFakeEmbedding(size=32)))
    monkeypatch.setattr(api, "demo_upload_limiter", RateLimiter(max_calls=100))
    monkeypatch.setattr(api, "answer_from_document",
                        lambda doc, question, llm: {"answer": f"from {doc.filename}", "groundedness_score": 0.8})
    return TestClient(api.app)


def upload(client, file=NOTE):
    return client.post("/demo/documents", files={"file": file})


def test_upload_then_query_round_trip(client):
    """Verify an upload returns a doc_id that answers questions about that document."""
    response = upload(client, ("Notes.TXT", NOTE[1], "text/plain"))
    assert response.status_code == 200
    body = response.json()
    assert (body["filename"], body["chunks"], body["expires_in"]) == ("notes.txt", 1, DEMO_TTL_SECONDS)

    answer = client.post(f"/demo/documents/{body['doc_id']}/query", json={"question": "Where do quokkas live?"})
    assert answer.status_code == 200
    assert answer.json() == {"question": "Where do quokkas live?", "answer": "from notes.txt",
                             "groundedness_score": 0.8}


def test_upload_rejects_unsupported_type(client):
    assert upload(client, ("tool.exe", b"MZ...", "application/octet-stream")).status_code == 415


def test_upload_rejects_oversized_file(client, monkeypatch):
    monkeypatch.setattr(api, "DEMO_MAX_FILE_BYTES", 10)
    assert upload(client).status_code == 413


def test_upload_rate_limit_returns_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(api, "demo_upload_limiter", RateLimiter(max_calls=1))
    assert upload(client).status_code == 200
    response = upload(client)
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_query_unknown_document_returns_404(client):
    response = client.post("/demo/documents/does-not-exist/query", json={"question": "Hi?"})
    assert response.status_code == 404


def test_query_empty_question_returns_400(client):
    doc_id = upload(client).json()["doc_id"]
    assert client.post(f"/demo/documents/{doc_id}/query", json={"question": "  "}).status_code == 400


def test_document_dropped_while_answering_returns_404(client, monkeypatch):
    """Verify the eviction race turns into 'upload again', not a server error."""
    doc_id = upload(client).json()["doc_id"]

    def evicted_mid_answer(doc, question, llm):
        api.demo_store._docs.clear()
        raise RuntimeError("collection deleted")

    monkeypatch.setattr(api, "answer_from_document", evicted_mid_answer)
    response = client.post(f"/demo/documents/{doc_id}/query", json={"question": "Where?"})
    assert response.status_code == 404
