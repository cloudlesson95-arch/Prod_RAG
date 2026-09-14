from typing import List
from sentence_transformers import CrossEncoder
from langchain_core.documents import Document
from src.config import RERANKER_MODEL, K_RETRIEVAL
from src.logging_config import setup_logging

logger = setup_logging(__name__)

# Global singleton instance for CrossEncoder model
_reranker_instance = None


def get_reranker() -> CrossEncoder:
    """Lazy initializer for CrossEncoder singleton model."""
    global _reranker_instance
    if _reranker_instance is None:
        logger.info(f"Loading CrossEncoder model '{RERANKER_MODEL}'...")
        _reranker_instance = CrossEncoder(RERANKER_MODEL)
    return _reranker_instance


def rerank_documents(
    query: str, documents: List[Document], top_k: int = K_RETRIEVAL
) -> List[Document]:
    """Re-rank candidate documents using Cross-Encoder model scoring.

    Args:
        query: User query string.
        documents: List of candidate Document objects retrieved in Stage 1.
        top_k: Number of highest-scoring documents to return.

    Returns:
        List[Document]: Top-k re-ranked documents.
    """
    if not documents:
        return []

    if len(documents) <= top_k:
        return documents

    model = get_reranker()

    # Form (query, document_text) pairs for cross-attention scoring
    pairs = [[query, doc.page_content] for doc in documents]
    scores = model.predict(pairs)

    # Combine documents with scores and sort descending
    doc_scores = list(zip(documents, scores))
    doc_scores.sort(key=lambda x: x[1], reverse=True)

    reranked_docs = [doc for doc, _ in doc_scores[:top_k]]
    top_score = doc_scores[0][1]
    lowest_kept_score = doc_scores[top_k - 1][1]

    logger.info(
        f"[Re-Ranker]: Re-ranked {len(documents)} candidates down to top-{top_k} "
        f"(scores: top={top_score:.3f}, cutoff={lowest_kept_score:.3f})."
    )
    return reranked_docs
