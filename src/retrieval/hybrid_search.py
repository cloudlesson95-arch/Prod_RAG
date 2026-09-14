import re
from typing import List, Dict, Any
from rank_bm25 import BM25Okapi
from langchain_core.documents import Document
from src.config import K_RETRIEVAL, K_CANDIDATES
from src.logging_config import setup_logging

logger = setup_logging(__name__)


def tokenize(text: str) -> List[str]:
    """Simple word tokenizer for BM25 indexing."""
    return re.findall(r"\w+", text.lower())


class BM25Index:
    """In-memory BM25 index built over LangChain Document objects."""

    def __init__(self, documents: List[Document]):
        self.documents = documents
        corpus = [tokenize(doc.page_content) for doc in documents]
        self.bm25 = BM25Okapi(corpus)

    def search(self, query: str, top_k: int = 12) -> List[Document]:
        """Search the BM25 index and return top_k matching Document objects."""
        if not self.documents:
            return []
        tokenized_query = tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)
        doc_scores = sorted(
            enumerate(scores), key=lambda x: x[1], reverse=True
        )
        top_indices = [idx for idx, score in doc_scores[:top_k] if score > 0]
        if not top_indices:
            top_indices = [idx for idx, _ in doc_scores[:top_k]]
        return [self.documents[idx] for idx in top_indices]


def reciprocal_rank_fusion(
    dense_results: List[Document],
    sparse_results: List[Document],
    top_k: int = 4,
    rrf_k: int = 60,
) -> List[Document]:
    """Fuse dense and sparse document lists using Reciprocal Rank Fusion (RRF).

    Formula: RRF_Score(d) = sum(1 / (rrf_k + rank(d)))
    """
    scores: Dict[str, float] = {}
    doc_map: Dict[str, Document] = {}

    def get_doc_key(doc: Document) -> str:
        source = doc.metadata.get("source", "unknown")
        return f"{source}::{doc.page_content.strip()}"

    # Process dense ranks
    for rank, doc in enumerate(dense_results):
        key = get_doc_key(doc)
        doc_map[key] = doc
        scores[key] = scores.get(key, 0.0) + (1.0 / (rrf_k + (rank + 1)))

    # Process sparse ranks
    for rank, doc in enumerate(sparse_results):
        key = get_doc_key(doc)
        doc_map[key] = doc
        scores[key] = scores.get(key, 0.0) + (1.0 / (rrf_k + (rank + 1)))

    # Sort documents by accumulated RRF score
    sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
    return [doc_map[k] for k in sorted_keys[:top_k]]


def hybrid_retrieve(
    vectorstore,
    query: str,
    source_filter: str = "none",
    top_k: int = K_RETRIEVAL,
    candidate_k: int = K_CANDIDATES,
) -> List[Document]:
    """Perform Hybrid Search: retrieve candidate chunks via Dense + BM25 and merge with RRF."""
    
    # Dense Vector Search
    search_kwargs = {"k": candidate_k}
    if source_filter and source_filter != "none":
        search_kwargs["filter"] = {"source": source_filter}

    dense_results = vectorstore.similarity_search(query, **search_kwargs)

    # Get all corpus chunks for BM25 indexing (filtered by source if set)
    where_filter = (
        {"source": source_filter}
        if (source_filter and source_filter != "none")
        else None
    )

    try:
        raw_data = vectorstore.get(where=where_filter)
        all_docs = [
            Document(page_content=text, metadata=meta)
            for text, meta in zip(raw_data["documents"], raw_data["metadatas"])
        ]
    except Exception as e:
        logger.warning(
            f"Failed to fetch documents for BM25 indexing: {e}. Falling back to dense results."
        )
        return dense_results[:top_k]

    if not all_docs:
        return dense_results[:top_k]

    # Sparse BM25 Search
    bm25_index = BM25Index(all_docs)
    sparse_results = bm25_index.search(query, top_k=candidate_k)

    # Reciprocal Rank Fusion
    fused_results = reciprocal_rank_fusion(
        dense_results, sparse_results, top_k=top_k
    )
    logger.info(
        f"[Hybrid Search]: Fused {len(dense_results)} dense + {len(sparse_results)} sparse "
        f"candidates into top-{len(fused_results)} final chunks (source filter: '{source_filter}')."
    )
    return fused_results
