from pydantic import BaseModel, Field
from typing import Literal
from src.config import (
    K_RETRIEVAL, K_CANDIDATES, MAX_RETRIES, EMBEDDING_LOCAL_MODEL, MAIN_LLM_MODEL,
    ROUTING_METHOD, ENABLE_SEMANTIC_CACHE, ENABLE_HYBRID_SEARCH, ENABLE_RERANKER,
    ENABLE_MULTI_HOP
)
from src.core.utils import create_llm
from src.retrieval.semantic_cache import check_cache, add_to_cache
from src.retrieval.hybrid_search import hybrid_retrieve
from src.retrieval.reranker import rerank_documents
from src.retrieval.multi_hop import execute_multi_hop_pipeline

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

def setup_router():
    """Setup the router LLM for determining data sources.
    
    Returns:
        The router LLM configured with structured output for RouteDecision.
    """    
    llm = create_llm(MAIN_LLM_MODEL)

    router_llm = llm.with_structured_output(RouteDecision)
    return router_llm

def retrieve_chunks(query: str, source_filter: str, vectorstore):
    """Retrieve top-k chunks using Hybrid Search and/or Re-Ranking."""
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

    return results

def retrieve_and_answer(query: str, source_filter: str, vectorstore, answer_llm) -> tuple[str, str]:
    """Retrieve relevant chunks and call answer LLM (supporting Multi-Hop if enabled).
    
    Returns:
        tuple[str, str]: (answer_text, context_text)
    """
    if ENABLE_MULTI_HOP:
        ans = execute_multi_hop_pipeline(
            question=query,
            initial_source=source_filter,
            vectorstore=vectorstore,
            answer_llm=answer_llm,
            retrieve_fn=lambda q, s: retrieve_chunks(q, s, vectorstore),
        )
        return ans, ""

    results = retrieve_chunks(query, source_filter, vectorstore)
    context_text = "\n---\n".join([doc.page_content for doc in results])
    logger.debug(f"Current context_text: {context_text}")

    prompt = f"""Answer ONLY based on the provided context.
    If the answer is not in the context, say "I don't know."

    Context:
    {context_text}

    Question: {query}
    Answer:"""
    return answer_llm.invoke(prompt).content, context_text


def answer_question(question: str, router, vectorstore, answer_llm, max_retries: int = MAX_RETRIES) -> str:
    """Answer a user question using RAG with self-correction.
    
    Args:
        question: The user's question to answer.
        router: The router LLM for determining data source.
        vectorstore: The vector store for retrieval.
        answer_llm: The LLM for generating answers.
        max_retries: Maximum number of rephrasing attempts (default: from config).
        
    Returns:
        str: The answer to the user's question.
    """
    if ENABLE_SEMANTIC_CACHE:
        query_vec = vectorstore._embedding_function.embed_query(question)
        hit, cached_answer, sim = check_cache(query_vec)
        if hit:
            logger.info(f"[Semantic Cache]: HIT (similarity {sim:.3f}) — skipping retrieval & LLM generation.")
            return cached_answer
        logger.info(f"[Semantic Cache]: MISS (highest similarity {sim:.3f})")

    source_filter = "none"
    context_text = ""

    if ROUTING_METHOD == "classical":
        from src.routing.classifier import predict_needs_retrieval_with_confidence
        from src.routing.clustering import predict_source

        query_embedding = vectorstore._embedding_function.embed_query(question)

        # Decision Point 1: Needs retrieval? (classifier)
        needs_retrieval, confidence = predict_needs_retrieval_with_confidence(query_embedding)
        logger.info(f"[Classical Router]: Retrieval decision={needs_retrieval} (Confidence: {confidence:.2f})")
        if not needs_retrieval:
            logger.info("[Classical Router]: No retrieval needed (Logistic Regression)")
            answer = answer_llm.invoke(question).content
        else:
            # Decision Point 2: Nearest source centroid (clustering)
            source_filter = predict_source(query_embedding)
            logger.info(f"[Classical Router]: Selected source '{source_filter}' (Nearest Centroid)")
            answer, context_text = retrieve_and_answer(question, source_filter, vectorstore, answer_llm)

    else: # Default: "llm"
        decision = router.invoke(question)
        logger.info(f"[Router]: '{decision.source}' ({decision.reasoning})")

        if decision.source == "none":
            logger.info("[Router] No retrieval needed")
            answer = answer_llm.invoke(question).content
        else:
            source_filter = decision.source
            answer, context_text = retrieve_and_answer(question, source_filter, vectorstore, answer_llm)

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

            answer, context_text = retrieve_and_answer(current_query, source_filter, vectorstore, answer_llm)

    # Groundedness Check
    if source_filter != "none" and "I don't know" not in answer and context_text:
        from src.monitoring.groundedness import score_groundedness
        from src.config import GROUNDEDNESS_THRESHOLD

        answer_emb = vectorstore._embedding_function.embed_query(answer)
        context_emb = vectorstore._embedding_function.embed_query(context_text)
        g_score = score_groundedness(answer_emb, context_emb)

        if g_score < GROUNDEDNESS_THRESHOLD:
            logger.warning(f"[Groundedness]: Low score {g_score:.3f} (threshold {GROUNDEDNESS_THRESHOLD:.2f})")
        else:
            logger.info(f"[Groundedness]: Score: {g_score:.3f}")

    if ENABLE_SEMANTIC_CACHE:
        if "I don't know" in answer:
             logger.info("[Semantic Cache]: Skipping caching for 'I don't know' answer.")
        else:
            add_to_cache(question, query_vec, answer)

    return answer
