from types import SimpleNamespace

import pytest

from src.core import rag_agent
from src.routing import classifier, corpus_probe, router

QUESTION = "Where does the quokka live?"


class FakeLLM:
    def __init__(self):
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return SimpleNamespace(content="Answered from general knowledge.")


@pytest.fixture
def routing(monkeypatch):
    """Classical routing with fakes: the classifier says 'no retrieval'; each test chooses the probe result."""
    retrieved_from = []

    def fake_retrieve_and_answer(query, source_filter, vectorstore, answer_llm):
        retrieved_from.append(source_filter)
        return "Rottnest Island.", ""

    monkeypatch.setattr(rag_agent, "ROUTING_METHOD", "classical")
    monkeypatch.setattr(rag_agent, "ENABLE_SEMANTIC_CACHE", False)
    monkeypatch.setattr(router, "CORPUS_PROBE_THRESHOLD", 0.55)
    monkeypatch.setattr(rag_agent, "retrieve_and_answer", fake_retrieve_and_answer)
    monkeypatch.setattr(classifier, "predict_needs_retrieval_with_confidence", lambda emb: (False, 0.54))
    vectorstore =SimpleNamespace(_embedding_function=SimpleNamespace(embed_query=lambda text: [1.0, 0.0]))
    return vectorstore, retrieved_from


def test_close_chunk_overrules_no_retrieval_and_picks_its_source(routing, monkeypatch):
    """Verify a probe hit forces retrieval from the closest chunk's source."""
    vectorstore, retrieved_from = routing
    monkeypatch.setattr(corpus_probe, "probe_corpus", lambda emb, vs: ("ingested/batch/quokka.txt", 0.75))
    llm = FakeLLM()

    answer = rag_agent.answer_question(QUESTION, None, vectorstore, llm)

    assert answer == "Rottnest Island."
    assert retrieved_from == ["ingested/batch/quokka.txt"]
    assert llm.prompts == []


def test_distant_chunk_keeps_no_retrieval(routing, monkeypatch):
    """Verify chit-chat-level similarity leaves the classifier's 'no retrieval' in place."""
    vectorstore, retrieved_from = routing
    monkeypatch.setattr(corpus_probe, "probe_corpus", lambda emb, vs: ("pydantic.llms-full.txt", 0.43))
    llm = FakeLLM()

    answer = rag_agent.answer_question(QUESTION, None, vectorstore, llm)

    assert answer == "Answered from general knowledge."
    assert retrieved_from == []
    assert llm.prompts == [QUESTION]


def test_classifier_yes_retrieves_from_the_closest_chunks_source(routing, monkeypatch):
    """Verify a 'retrieve' vote searches the closest chunk's source even when that chunk is below the threshold."""
    vectorstore, retrieved_from = routing
    monkeypatch.setattr(classifier, "predict_needs_retrieval_with_confidence", lambda emb: (True, 0.60))
    monkeypatch.setattr(corpus_probe, "probe_corpus", lambda emb, vs: ("ingested/batch/quokka.txt", 0.40))

    rag_agent.answer_question(QUESTION, None, vectorstore, FakeLLM())
    assert retrieved_from == ["ingested/batch/quokka.txt"]
