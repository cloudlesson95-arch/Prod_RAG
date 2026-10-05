from src.ingestion import questions
from src.ingestion.questions import GeneratedQA


class FakeWriter:
    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeLLM:
    """Stands in for a LangChain chat model; replies are GeneratedQA objects or exceptions, in call order."""

    def __init__(self, replies):
        self.writer, self.schema = FakeWriter(replies), None

    def with_structured_output(self, schema):
        self.schema = schema
        return self.writer


def _doc(paragraphs):
    """One ~400-character paragraph per chunk, so chunk i is 'Fact i: ...'."""
    return "\n\n".join(f"Fact {i}: " + "Quokkas live on Rottnest Island near Perth. " * 9 for i in range(paragraphs))


def test_spread_samples_evenly_and_keeps_short_lists():
    """Verify first/middle/last sampling, a single pick from the middle, and no padding for short lists."""
    assert questions._spread(list(range(10)), 3) == [0, 4, 9]
    assert questions._spread(list(range(10)), 1) == [5]
    assert questions._spread([1, 2], 5) == [1, 2]


def test_questions_cover_the_whole_document():
    """Verify chunks are sampled across the document, not just from its start, and each pair keeps its chunk."""
    llm = FakeLLM([GeneratedQA(question=f"Question {i}?", answer="An answer.") for i in range(3)])

    pairs = questions.generate_questions(_doc(10), llm, n=3)

    assert llm.schema is GeneratedQA
    assert [pair["context"].split(":")[0] for pair in pairs] == ["Fact 0", "Fact 4", "Fact 9"]


def test_failed_vague_and_empty_pairs_are_skipped():
    """Verify a failing call, a question about 'the passage' and an empty question cost only their own chunk."""
    llm = FakeLLM([
        GeneratedQA(question="Where do quokkas live?", answer="On Rottnest Island."),
        RuntimeError("429 rate limited"),
        GeneratedQA(question="What does the passage say about Perth?", answer="It is nearby."),
        GeneratedQA(question="  ", answer="Nothing."),
    ])

    pairs = questions.generate_questions(_doc(4), llm, n=4)

    assert pairs == [{"question": "Where do quokkas live?", "answer": "On Rottnest Island.",
                      "context": _doc(4).split("\n\n")[0].strip()}]
    assert "Fact 0:" in llm.writer.prompts[0] and "Fact 3:" in llm.writer.prompts[3]


def test_short_chunks_never_reach_the_llm():
    """Verify headings and other chunks under the minimum length cost no LLM call."""
    llm = FakeLLM([])
    assert questions.generate_questions("# Title\n\nShort line.", llm) == []
    assert llm.writer.prompts == []
