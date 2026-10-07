from dataclasses import dataclass, field
from pydantic import BaseModel, Field
from typing import Literal
from src.config import (
    K_RETRIEVAL, K_CANDIDATES, MAX_RETRIES, EMBEDDING_LOCAL_MODEL, MAIN_LLM_MODEL,
    ROUTING_METHOD, ENABLE_SEMANTIC_CACHE, ENABLE_HYBRID_SEARCH, ENABLE_RERANKER,
    ENABLE_MULTI_HOP, GROUNDEDNESS_THRESHOLD
)
from src.core.utils import create_llm
from src.monitoring.groundedness import chunk_similarities
from src.retrieval.semantic_cache import check_cache, add_to_cache
from src.retrieval.hybrid_search import hybrid_retrieve
from src.retrieval.reranker import rerank_documents
from src.retrieval.multi_hop import execute_multi_hop_pipeline
from src.retrieval import versions

from src.logging_config import setup_logging
logger = setup_logging(__name__)

class RouteDecision(BaseModel):
    """Decides which data source to use based on the user's query."""

    source: Literal["pydantic.llms-full.txt", "cat-facts.txt", "fictional_text.txt", "none"] = Field(
        description="""Which data source:
        - 'pydantic.llms-full.txt': questions about Python, AI, Pydantic, Anthropic, LLMs, agents, models and their values and parameters 
        - 'cat-facts.txt': questions about cats, animals, pets
        - 'fictional_text.txt': questions about Oakhaven, pumpkin festival, city council, Elena Rostova
        - 'none': basic knowledge, regular math, greetings, or anything not in the above"""
    )

    reasoning: str = Field(
        description="A short 1-sentence explanation of why you chose this source."
    )


@dataclass
class Passage:
    """One retrieved chunk an answer was generated from."""
    source: str
    text: str
    similarity: float | None = None  # cosine similarity to the answer; None when the answer wasn't scored


@dataclass
class AnswerResult:
    """An answer and how it was produced: what /query returns, and what the query CLI and the evaluator read."""
    answer: str
    source: str | None = None                # source searched; "none" when the router chose no retrieval; None on a cache hit
    route_reason: str | None = None          # RouteResult.reason, or "llm" with ROUTING_METHOD=llm
    router_confidence: float | None = None   # the classifier's raw probability for its own vote (uncalibrated)
    probe_similarity: float | None = None    # cosine similarity of the closest chunk in the corpus
    groundedness_score: float | None = None  # answer-context similarity: the best passage's similarity to the answer
    cache_hit: bool = False
    passages: list[Passage] = field(default_factory=list)

def setup_router():
    """Setup the router LLM for determining data sources.
    
    Returns:
        The router LLM configured with structured output for RouteDecision.
    """    
    llm = create_llm(MAIN_LLM_MODEL)

    router_llm = llm.with_structured_output(RouteDecision)
    return router_llm

def retrieve_chunks(query: str, source_filter: str, vectorstore):
    """Retrieve top-k chunks using Hybrid Search and/or Re-Ranking.

    A question that names a release ("v2.51.0") gets that release's own chunks first: neither the
    embeddings nor the reranker tell version numbers apart, so those chunks would otherwise lose to
    similar chunks from other releases.
    """
    named = versions.chunks_of_named_release(vectorstore, query, source_filter)
    if len(named) >= K_RETRIEVAL:
        logger.info(f"[Retrieval]: Question names a release; choosing among its {len(named)} chunks")
        return rerank_documents(query, named, top_k=K_RETRIEVAL) if ENABLE_RERANKER else named[:K_RETRIEVAL]

    fetch_k = K_CANDIDATES if ENABLE_RERANKER else K_RETRIEVAL

    if ENABLE_HYBRID_SEARCH:
        results = hybrid_retrieve(
            vectorstore,
            query,
            source_filter=source_filter,
            top_k=fetch_k,
            candidate_k=K_CANDIDATES,
        )
    else:
        search_kwargs = {"k": fetch_k}
        if source_filter and source_filter != "none":
            search_kwargs["filter"] = {"source": source_filter}
        results = vectorstore.similarity_search(query, **search_kwargs)

    if ENABLE_RERANKER:
        results = rerank_documents(query, results, top_k=K_RETRIEVAL)
    else:
        results = results[:K_RETRIEVAL]

    if named:  # a release with only a few chunks: all of them first, then the best of the rest
        kept = {doc.page_content for doc in named}
        results = (named + [doc for doc in results if doc.page_content not in kept])[:K_RETRIEVAL]
    return results

def retrieve_and_answer(query: str, source_filter: str, vectorstore, answer_llm) -> tuple[str, list]:
    """Retrieve relevant chunks and call answer LLM (supporting Multi-Hop if enabled).

    Returns:
        tuple[str, list]: (answer_text, the retrieved chunks the answer was generated from)
    """
    if ENABLE_MULTI_HOP:
        return execute_multi_hop_pipeline(
            question=query,
            initial_source=source_filter,
            vectorstore=vectorstore,
            answer_llm=answer_llm,
            retrieve_fn=lambda q, s: retrieve_chunks(q, s, vectorstore),
        )

    results = retrieve_chunks(query, source_filter, vectorstore)
    context_text = "\n---\n".join([doc.page_content for doc in results])
    logger.debug(f"Current context_text: {context_text}")

    prompt = f"""Answer ONLY based on the provided context.
    If the answer is not in the context, say "I don't know."

    Context:
    {context_text}

    Question: {query}
    Answer:"""
    return answer_llm.invoke(prompt).content, results


def score_passages(passages: list[Passage], answer: str, embeddings) -> float:
    """Set each passage's similarity to the answer and return the best one, the answer-context similarity.

    A topic match, not a fact check: it can't tell "right topic, wrong number" from a correct answer.
    """
    scores = chunk_similarities(embeddings.embed_query(answer), embeddings.embed_documents([p.text for p in passages]))
    for passage, score in zip(passages, scores):
        passage.similarity = score
    return max(scores)


def answer_question(question: str, router, vectorstore, answer_llm, max_retries: int = MAX_RETRIES) -> AnswerResult:
    """Answer a user question using RAG with self-correction.
    
    Args:
        question: The user's question to answer.
        router: The router LLM for determining data source.
        vectorstore: The vector store for retrieval.
        answer_llm: The LLM for generating answers.
        max_retries: Maximum number of rephrasing attempts (default: from config).
        
    Returns:
        AnswerResult: The answer, the routing decision behind it, and the passages it was generated from.
    """
    if ENABLE_SEMANTIC_CACHE:
        query_vec = vectorstore._embedding_function.embed_query(question)
        hit, cached_answer, sim = check_cache(query_vec)
        if hit:
            logger.info(f"[Semantic Cache]: HIT (similarity {sim:.3f}) — skipping retrieval & LLM generation.")
            return AnswerResult(answer=cached_answer, cache_hit=True)
        logger.info(f"[Semantic Cache]: MISS (highest similarity {sim:.3f})")

    source_filter = "none"
    docs = []
    router_confidence = probe_similarity = None

    if ROUTING_METHOD == "classical":
        # Imported here, not at the top: classifier -> evaluator -> rag_agent would be circular
        from src.routing.router import decide_route

        query_embedding = vectorstore._embedding_function.embed_query(question)
        route = decide_route(query_embedding, vectorstore, query=question)
        route_reason, router_confidence, probe_similarity = route.reason, route.confidence, route.probe_similarity

        if not route.needs_retrieval:
            answer = answer_llm.invoke(question).content
        else:
            source_filter = route.source
            answer, docs = retrieve_and_answer(question, source_filter, vectorstore, answer_llm)

    else: # Default: "llm"
        decision = router.invoke(question)
        logger.info(f"[Router]: '{decision.source}' ({decision.reasoning})")
        route_reason = "llm"

        if decision.source == "none":
            logger.info("[Router] No retrieval needed")
            answer = answer_llm.invoke(question).content
        else:
            source_filter = decision.source
            answer, docs = retrieve_and_answer(question, source_filter, vectorstore, answer_llm)

    current_query = question
    # Self-Correction loop
    for attempt in range(max_retries):
        if "I don't know" in answer:
            logger.info(f"[Agent] Attempt {attempt + 1}/{max_retries}: answer insufficient, rephrasing...")
            logger.debug(f"Current answer: {answer}")

            rephrase_prompt = f"""The user asked: "{current_query}"
            A search returned no useful results. 
            Rephrase this question using different keywords.
            Return ONLY the rephrased question."""

            current_query = answer_llm.invoke(rephrase_prompt).content.strip()
            logger.info(f"[Agent] Rephrased query: '{current_query}'")

            answer, docs = retrieve_and_answer(current_query, source_filter, vectorstore, answer_llm)

    # Groundedness Check (answer-context similarity)
    passages = [Passage(doc.metadata.get("source", "unknown"), doc.page_content) for doc in docs]
    g_score = None
    if passages and "I don't know" not in answer:
        g_score = score_passages(passages, answer, vectorstore._embedding_function)

        if g_score < GROUNDEDNESS_THRESHOLD:
            logger.warning(f"[Groundedness]: Low score {g_score:.3f} (threshold {GROUNDEDNESS_THRESHOLD:.2f})")
        else:
            logger.info(f"[Groundedness]: Score: {g_score:.3f}")

    if ENABLE_SEMANTIC_CACHE:
        if not answer.strip():
            logger.warning("[Semantic Cache]: Skipping caching for an empty answer.")
        elif "I don't know" in answer:
             logger.info("[Semantic Cache]: Skipping caching for 'I don't know' answer.")
        else:
            add_to_cache(question, query_vec, answer)

    return AnswerResult(answer=answer, source=source_filter, route_reason=route_reason,
                        router_confidence=router_confidence, probe_similarity=probe_similarity,
                        groundedness_score=g_score, passages=passages)
