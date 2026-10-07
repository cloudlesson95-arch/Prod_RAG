from types import SimpleNamespace

import pytest
from langchain_chroma import Chroma
from langchain_core.embeddings import DeterministicFakeEmbedding

from src.core import rag_agent
from src.ingestion.demo import DemoStore, answer_from_document

TEXT = "Quokkas live on Rottnest Island and are known for their smiles. " * 40


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def embeddings():
    return DeterministicFakeEmbedding(size=32)


def test_added_document_is_chunked_and_searchable(embeddings):
    """Verify an upload is split into chunks that are searchable in its own collection."""
    store = DemoStore(embeddings)
    doc = store.add("quokkas.txt", TEXT)

    assert doc.chunks > 1
    assert store.get(doc.doc_id) is doc
    hits = doc.vectorstore.similarity_search("Where do quokkas live?", k=2)
    assert {h.metadata["source"] for h in hits} == {"quokkas.txt"}


def test_documents_expire_after_idle_ttl(embeddings):
    """Verify each use restarts the TTL and an idle document disappears."""
    clock = FakeClock()
    store = DemoStore(embeddings, ttl_seconds=60, clock=clock)
    doc = store.add("a.txt", TEXT)

    clock.now += 59
    assert store.get(doc.doc_id) is doc
    clock.now += 59
    assert store.get(doc.doc_id) is doc
    clock.now += 60
    assert store.get(doc.doc_id) is None


def test_least_recently_used_document_is_evicted_at_capacity(embeddings):
    """Verify the store drops the least recently used document, not the oldest upload."""
    store = DemoStore(embeddings, max_docs=2)
    a = store.add("a.txt", TEXT)
    b = store.add("b.txt", TEXT)
    store.get(a.doc_id)
    c = store.add("c.txt", TEXT)

    assert store.get(b.doc_id) is None
    assert store.get(a.doc_id) is a
    assert store.get(c.doc_id) is c


def test_demo_documents_never_reach_the_persistent_index(embeddings, tmp_path):
    """Verify demo uploads and the shared on-disk index don't see each other."""
    persistent = Chroma(persist_directory=str(tmp_path / "chroma_db"), embedding_function=embeddings)
    persistent.add_texts(["Cats sleep a lot."], metadatas=[{"source": "cat-facts.txt"}])

    doc = DemoStore(embeddings).add("secret.txt", TEXT)

    assert persistent._collection.count() == 1
    assert {m["source"] for m in persistent.get()["metadatas"]} == {"cat-facts.txt"}
    assert {m["source"] for m in doc.vectorstore.get()["metadatas"]} == {"secret.txt"}


def test_answer_uses_only_the_uploaded_document(embeddings, monkeypatch):
    """Verify the answer prompt is built from the document's chunks, which come back scored as its passages."""
    monkeypatch.setattr(rag_agent, "ENABLE_RERANKER", False)  # keeps the cross-encoder model out of unit tests
    prompts = []

    class FakeLLM:
        def invoke(self, prompt):
            prompts.append(prompt)
            return SimpleNamespace(content="They live on Rottnest Island.")

    doc = DemoStore(embeddings).add("quokkas.txt", TEXT)
    result = answer_from_document(doc, "Where do quokkas live?", FakeLLM())

    assert result["answer"] == "They live on Rottnest Island."
    assert "Rottnest Island" in prompts[0]
    assert {p["source"] for p in result["passages"]} == {"quokkas.txt"}
    assert result["groundedness_score"] == max(p["similarity"] for p in result["passages"])
