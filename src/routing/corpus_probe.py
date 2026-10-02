import numpy as np


def probe_corpus(query_embedding, vectorstore) -> tuple[str | None, float]:
    """Find the single indexed chunk closest to a query.

    The retrieval classifier is trained on fixed example questions and never sees the corpus,
    so this is the corpus's own vote: a high similarity means some indexed document covers
    the query's topic, including documents ingested after the classifier was trained.

    Returns:
        tuple: (source of the closest chunk, or None if the index is empty; their cosine similarity)
    """
    results = vectorstore._collection.query(
        query_embeddings=[query_embedding], n_results=1, include=["embeddings", "metadatas"]
    )
    if not results["ids"][0]:
        return None, 0.0

    query_vec = np.asarray(query_embedding, dtype=float)
    chunk_vec = np.asarray(results["embeddings"][0][0], dtype=float)
    similarity = float(np.dot(query_vec, chunk_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(chunk_vec)))
    return results["metadatas"][0][0].get("source"), similarity
