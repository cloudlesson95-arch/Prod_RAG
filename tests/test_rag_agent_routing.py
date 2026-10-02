from types import SimpleNamespace

import pytest

from src.core import rag_agent
from src.routing import classifier, clustering, corpus_probe

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
    monkeypatch.setattr(rag_agent, "CORPUS_PROBE_THRESHOLD", 0.55)
    monkeypatch.setattr(rag_agent, "retrieve_and_answer", fake_retrieve_and_answer)
    monkeypatch.setattr(classifier, "predict_needs_retrieval_with_confidence", lambda emb: (False, 0.54))
    monkeypatch.setattr(clustering, "predict_source", lambda emb: "ingested/batch/quokka.txt")
    vectorstore = SimpleNamespace(_embedding_function=SimpleNamespace(embed_query=lambda text: [1.0, 0.0]))
    return vectorstore, retrieved_from


def test_close_chunk_overrules_no_retrieval_and_centroid_picks_source(routing, monkeypatch):
    """Verify a probe hit forces retrieval from the centroid's source, not the probe chunk's source."""
    vectorstore, retrieved_from = routing
    monkeypatch.setattr(corpus_probe, "probe_corpus", lambda emb, vs: ("pydantic.llms-full.txt", 0.75))
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


def test_probe_is_skipped_when_classifier_already_retrieves(routing, monkeypatch):
    """Verify the probe costs nothing on questions the classifier already routes to retrieval."""
    vectorstore, retrieved_from = routing
    monkeypatch.setattr(classifier, "predict_needs_retrieval_with_confidence", lambda emb: (True, 0.60))

    def probe_must_not_run(emb, vs):
        raise AssertionError("probe ran although the classifier said retrieve")

    monkeypatch.setattr(corpus_probe, "probe_corpus", probe_must_not_run)

    rag_agent.answer_question(QUESTION, None, vectorstore, FakeLLM())
    assert retrieved_from == ["ingested/batch/quokka.txt"]
