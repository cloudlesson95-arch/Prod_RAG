from types import SimpleNamespace

from langchain_core.documents import Document

from src.retrieval.multi_hop import MultiHopAnalysis, execute_multi_hop_pipeline

QUESTION = "Who runs the pumpkin festival, and when is it?"
FOLLOW_UP = "When is the pumpkin festival?"


class FakeLLM:
    """Finds the first hop's context incomplete, then answers from whatever context it gets."""

    def with_structured_output(self, schema):
        return SimpleNamespace(invoke=lambda prompt: MultiHopAnalysis(
            is_complete=False, reasoning="the date is missing", follow_up_query=FOLLOW_UP,
            next_source="fictional_text.txt"))

    def invoke(self, prompt):
        return SimpleNamespace(content="The city council, on October 31st.")


def test_returns_the_answer_with_the_deduplicated_chunks_of_every_hop():
    """Verify the pipeline returns the chunks it answered from, each once, in the order the hops found them."""
    hops = {QUESTION: [Document(page_content="a"), Document(page_content="b")],
            FOLLOW_UP: [Document(page_content="b"), Document(page_content="c")]}
    calls = []

    def retrieve(query, source):
        calls.append((query, source))
        return hops[query]

    answer, docs = execute_multi_hop_pipeline(QUESTION, "none", None, FakeLLM(), retrieve, max_hops=2)

    assert answer == "The city council, on October 31st."
    assert [d.page_content for d in docs] == ["a", "b", "c"]
    assert calls == [(QUESTION, "none"), (FOLLOW_UP, "fictional_text.txt")]
