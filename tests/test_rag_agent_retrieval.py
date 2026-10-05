import pytest
from langchain_core.documents import Document

from src.core import rag_agent


def _docs(*texts):
    return [Document(page_content=text, metadata={"source": "ingested/batch/releases.md"}) for text in texts]


def test_a_named_release_with_enough_chunks_is_searched_alone(monkeypatch):
    """Verify a question naming a release reranks only that release's chunks and skips the general search."""
    named = _docs("* [v2.51.0] a", "* [v2.51.0] b", "* [v2.51.0] c", "* [v2.51.0] d", "* [v2.51.0] e")
    reranked = []
    monkeypatch.setattr(rag_agent, "ENABLE_RERANKER", True)
    monkeypatch.setattr(rag_agent.versions, "chunks_of_named_release", lambda vs, q, s: named)
    monkeypatch.setattr(rag_agent, "hybrid_retrieve", lambda *args, **kwargs: pytest.fail("general search ran"))
    monkeypatch.setattr(rag_agent, "rerank_documents", lambda q, docs, top_k: reranked.append(docs) or docs[:top_k])

    results = rag_agent.retrieve_chunks("What changed in v2.51.0?", "ingested/batch/releases.md", vectorstore=None)

    assert reranked == [named]
    assert [d.page_content for d in results] == ["* [v2.51.0] a", "* [v2.51.0] b", "* [v2.51.0] c", "* [v2.51.0] d"]


def test_a_small_named_release_comes_first_then_the_best_of_the_rest(monkeypatch):
    """Verify a release with fewer chunks than K keeps all of them, first and without duplicates, then general results."""
    named = _docs("* [v1.107.7] security fix")
    monkeypatch.setattr(rag_agent, "ENABLE_RERANKER", True)
    monkeypatch.setattr(rag_agent, "ENABLE_HYBRID_SEARCH", True)
    monkeypatch.setattr(rag_agent.versions, "chunks_of_named_release", lambda vs, q, s: named)
    monkeypatch.setattr(rag_agent, "hybrid_retrieve",
                        lambda *args, **kwargs: _docs("x", "* [v1.107.7] security fix", "y", "z", "w"))
    monkeypatch.setattr(rag_agent, "rerank_documents", lambda q, docs, top_k: docs[:top_k])

    results = rag_agent.retrieve_chunks("What shipped in v1.107.7?", "ingested/batch/releases.md", vectorstore=None)

    assert [d.page_content for d in results] == ["* [v1.107.7] security fix", "x", "y", "z"]
