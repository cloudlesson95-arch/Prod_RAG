from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

from src.core import rag_agent
from src.routing import router

QUESTION = "What is a group of cats called?"
CHUNKS = [Document(page_content="A group of cats is called a clowder.", metadata={"source": "cat-facts.txt"}),
          Document(page_content="Cats sleep 12 to 16 hours a day.", metadata={"source": "cat-facts.txt"})]


class FakeEmbeddings:
    """Every query (the question, the answer) points along x; of the chunks, only the clowder one does too."""

    def embed_query(self, text):
        return [1.0, 0.0]

    def embed_documents(self, texts):
        return [[1.0, 0.0] if "clowder" in text else [0.0, 1.0] for text in texts]


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply

    def invoke(self, prompt):
        return SimpleNamespace(content=self.reply)


@pytest.fixture
def vectorstore(monkeypatch):
    """Classical routing to cat-facts.txt with fakes; retrieval returns CHUNKS and the LLM's reply."""
    monkeypatch.setattr(rag_agent, "ROUTING_METHOD", "classical")
    monkeypatch.setattr(rag_agent, "ENABLE_SEMANTIC_CACHE", False)
    monkeypatch.setattr(router, "decide_route",
                        lambda emb, vs, query="": router.RouteResult(True, "cat-facts.txt", 0.9, 0.62, "classifier"))
    monkeypatch.setattr(rag_agent, "retrieve_and_answer",
                        lambda query, source, vs, llm: (llm.invoke(query).content, list(CHUNKS)))
    return SimpleNamespace(_embedding_function=FakeEmbeddings())


def test_retrieved_answer_reports_its_route_and_scored_passages(vectorstore):
    """Verify the result carries the routing decision, each passage's similarity, and the best one as the score."""
    result = rag_agent.answer_question(QUESTION, None, vectorstore, FakeLLM("A clowder."))

    assert result.answer == "A clowder."
    assert (result.source, result.route_reason, result.router_confidence, result.probe_similarity) == \
        ("cat-facts.txt", "classifier", 0.9, 0.62)
    assert [(p.source, p.text) for p in result.passages] == [(d.metadata["source"], d.page_content) for d in CHUNKS]
    assert [p.similarity for p in result.passages] == pytest.approx([1.0, 0.0])
    assert result.groundedness_score == pytest.approx(1.0)
    assert result.cache_hit is False


def test_i_dont_know_keeps_the_passages_unscored(vectorstore):
    """Verify an "I don't know" answer gets no similarity score but still shows what was searched."""
    result = rag_agent.answer_question(QUESTION, None, vectorstore, FakeLLM("I don't know."), max_retries=0)

    assert len(result.passages) == 2
    assert result.groundedness_score is None
    assert all(p.similarity is None for p in result.passages)


def test_cache_hit_returns_only_the_answer(vectorstore, monkeypatch):
    """Verify a semantic cache hit skips routing and reports no route or passages."""
    monkeypatch.setattr(rag_agent, "ENABLE_SEMANTIC_CACHE", True)
    monkeypatch.setattr(rag_agent, "check_cache", lambda vec: (True, "A clowder.", 0.97))
    monkeypatch.setattr(router, "decide_route", lambda *args, **kwargs: pytest.fail("routed on a cache hit"))

    result = rag_agent.answer_question(QUESTION, None, vectorstore, FakeLLM("unused"))

    assert result == rag_agent.AnswerResult(answer="A clowder.", cache_hit=True)


def test_llm_routing_reports_its_source_without_classifier_scores(vectorstore, monkeypatch):
    """Verify ROUTING_METHOD=llm fills the source and reason "llm" and leaves the classifier fields empty."""
    monkeypatch.setattr(rag_agent, "ROUTING_METHOD", "llm")
    llm_router = SimpleNamespace(invoke=lambda q: rag_agent.RouteDecision(source="cat-facts.txt", reasoning="cats"))

    result = rag_agent.answer_question(QUESTION, llm_router, vectorstore, FakeLLM("A clowder."))

    assert (result.source, result.route_reason) == ("cat-facts.txt", "llm")
    assert result.router_confidence is None and result.probe_similarity is None


@pytest.mark.parametrize("reply, cached", [("A clowder.", ["A clowder."]), ("", []), ("  \n", [])])
def test_only_non_empty_answers_are_cached(vectorstore, monkeypatch, reply, cached):
    """Verify a real answer is cached, while an empty LLM reply is returned without being cached."""
    monkeypatch.setattr(rag_agent, "ENABLE_SEMANTIC_CACHE", True)
    monkeypatch.setattr(rag_agent, "check_cache", lambda vec: (False, None, 0.0))
    stored = []
    monkeypatch.setattr(rag_agent, "add_to_cache", lambda question, vec, answer: stored.append(answer))

    result = rag_agent.answer_question(QUESTION, None, vectorstore, FakeLLM(reply), max_retries=0)

    assert result.answer == reply
    assert stored == cached
