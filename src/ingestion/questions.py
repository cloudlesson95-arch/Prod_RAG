import time

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field

from src.config import CHUNK_OVERLAP, CHUNK_SIZE, QUESTION_GEN_PAUSE_SECONDS, QUESTIONS_PER_DOC
from src.logging_config import setup_logging

logger = setup_logging(__name__)

MIN_CHUNK_CHARS = 200  # shorter chunks (headings, link lists) rarely hold a fact worth a question
# Questions that point at the passage instead of naming their subject are useless as routing examples
_VAGUE_REFERENCES = ("passage", "this text", "the text", "this excerpt", "this section", "the above", "the snippet")

PROMPT = """You write test questions for a search system.

Read the passage and write ONE question a user might ask that this passage answers, plus a short answer.
Rules:
- The question must make sense on its own: name its subject (a product, class, place, person...), and never say "the passage", "the text" or "this section".
- The passage alone must be enough to answer it.
- The answer is one short sentence or phrase taken from the passage.

Passage:
{chunk}"""


class GeneratedQA(BaseModel):
    """One question a user might ask that the passage answers, with its short answer."""

    question: str = Field(description="A self-contained question that names its subject, answerable from the passage alone.")
    answer: str = Field(description="A short answer taken from the passage.")


def _spread(items: list, n: int) -> list:
    """n items evenly spaced across the list, or all of them if there aren't more than n."""
    if len(items) <= n:
        return list(items)
    if n == 1:
        return [items[len(items) // 2]]
    return [items[round(k * (len(items) - 1) / (n - 1))] for k in range(n)]


def generate_questions(text: str, llm, n: int = QUESTIONS_PER_DOC) -> list[dict]:
    """Have the LLM write up to n question/answer pairs about a document, one per sampled chunk.

    Chunks are split the way the index splits them and sampled evenly, so the questions cover the whole
    document. A chunk whose call fails, or whose question points at the passage instead of naming its
    subject, is skipped.

    Returns:
        list[dict]: {'question', 'answer', 'context'} per kept pair; 'context' is the chunk it came from.
    """
    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, length_function=len)
    chunks = [chunk for chunk in splitter.split_text(text) if len(chunk) >= MIN_CHUNK_CHARS]
    writer = llm.with_structured_output(GeneratedQA)

    pairs = []
    for i, chunk in enumerate(_spread(chunks, n)):
        if i and QUESTION_GEN_PAUSE_SECONDS:
            time.sleep(QUESTION_GEN_PAUSE_SECONDS)
        try:
            qa = writer.invoke(PROMPT.format(chunk=chunk))
            question, answer = qa.question.strip(), qa.answer.strip()
        except Exception as e:  # provider errors, rate limits after the client's retries, unparsable output
            logger.warning(f"[Questions] Skipping a chunk, generation failed: {e}")
            continue
        if not question or not answer or any(ref in question.lower() for ref in _VAGUE_REFERENCES):
            logger.warning(f"[Questions] Skipping a vague or empty pair: {question!r}")
            continue
        pairs.append({"question": question, "answer": answer, "context": chunk})
    return pairs
