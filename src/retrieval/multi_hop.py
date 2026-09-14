from typing import Literal, List, Any, Callable
from pydantic import BaseModel, Field
from src.config import MAX_HOPS
from src.logging_config import setup_logging

logger = setup_logging(__name__)


class MultiHopAnalysis(BaseModel):
    """Structured evaluation of whether retrieved context is sufficient or requires an additional retrieval hop."""

    is_complete: bool = Field(
        description="True if the provided context contains all necessary facts to fully answer the user question. False if key facts or multiple parts of the question are missing."
    )
    reasoning: str = Field(
        description="A short 1-sentence explanation of what information is present vs what is missing."
    )
    follow_up_query: str = Field(
        default="",
        description="If is_complete is False, a targeted sub-query to find the missing fact. If is_complete is True, return an empty string.",
    )
    next_source: Literal[
        "pydantic.llms-full.txt", "cat-facts.txt", "fictional_text.txt", "none"
    ] = Field(
        default="none",
        description="Which data source to query for the missing information.",
    )


def analyze_context_completeness(
    question: str, context_text: str, llm
) -> MultiHopAnalysis:
    """Evaluate whether retrieved context completely answers the user question using structured output."""
    evaluator_llm = llm.with_structured_output(MultiHopAnalysis)
    prompt = f"""You are a multi-hop RAG context evaluator.
Inspect the provided context against the user question.

Question: {question}

Context:
{context_text}

Determine if the context contains all necessary information to fully answer the question."""

    return evaluator_llm.invoke(prompt)


def execute_multi_hop_pipeline(
    question: str,
    initial_source: str,
    vectorstore,
    answer_llm,
    retrieve_fn: Callable[[str, str], List[Any]],
    max_hops: int = MAX_HOPS,
) -> str:
    """Execute an iterative multi-hop retrieval loop up to max_hops."""
    current_source = initial_source
    current_query = question
    context_docs = []
    existing_texts = set()

    for hop in range(1, max_hops + 1):
        docs = retrieve_fn(current_query, current_source)
        for doc in docs:
            if doc.page_content not in existing_texts:
                context_docs.append(doc)
                existing_texts.add(doc.page_content)

        current_context = "\n---\n".join([doc.page_content for doc in context_docs])

        # If we reached max_hops, break loop and generate final answer
        if hop == max_hops:
            logger.info(f"[Multi-Hop Agent]: Reached MAX_HOPS ({max_hops}). Finalizing answer.")
            break

        # Evaluate context completeness
        try:
            analysis = analyze_context_completeness(question, current_context, answer_llm)
        except Exception as e:
            logger.warning(f"[Multi-Hop Agent]: Context evaluation failed ({e}). Stopping hops.")
            break

        if analysis.is_complete:
            logger.info(f"[Multi-Hop Agent]: Context complete at Hop {hop}.")
            break
        else:
            logger.info(
                f"[Multi-Hop Agent]: Hop {hop} incomplete ({analysis.reasoning}). "
                f"Executing Hop {hop + 1} query: '{analysis.follow_up_query}' on source '{analysis.next_source}'"
            )
            current_query = analysis.follow_up_query
            current_source = analysis.next_source

    final_context = "\n---\n".join([doc.page_content for doc in context_docs])
    prompt = f"""Answer ONLY based on the provided context.
If the answer is not in the context, say "I don't know."

Context:
{final_context}

Question: {question}
Answer:"""

    return answer_llm.invoke(prompt).content
