import numpy as np

# Exact nearest-chunk search. Chroma's HNSW top-1 is approximate and missed freshly ingested chunks
# The corpus only changes between restarts or inside one CLI write, so one cached matrix is enough;
# it reloads when the collection or its chunk count changes.
_cache: dict = {"key": None, "matrix": None, "sources": None}


def _corpus_matrix(collection) -> tuple[np.ndarray, list]:
    """Return the collection's row-normalized embeddings and the source of each row."""
    key = (collection.id, collection.count())
    if _cache["key"] != key:
        data = collection.get(include=["embeddings", "metadatas"])
        embeddings = data.get("embeddings")
        if embeddings is None or len(embeddings) == 0:
            matrix, sources = np.empty((0, 0), dtype=np.float32), []
        else:
            matrix = np.asarray(embeddings, dtype=np.float32)
            matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
            sources = [m.get("source") for m in data["metadatas"]]
        _cache.update(key=key, matrix=matrix, sources=sources)
    return _cache["matrix"], _cache["sources"]


def probe_corpus(query_embedding, vectorstore) -> tuple[str | None, float]:
    """Find the single indexed chunk closest to a query, by exact cosine similarity.

    The retrieval classifier is trained on fixed example questions and never sees the corpus,
    so this is the corpus's own vote: a high similarity means some indexed document covers
    the query's topic, including documents ingested after the classifier was trained.

    Returns:
        tuple: (source of the closest chunk, or None if the index is empty; their cosine similarity)
    """
    matrix, sources = _corpus_matrix(vectorstore._collection)
    if not sources:
        return None, 0.0

    query_vec = np.asarray(query_embedding, dtype=np.float32)
    similarities = matrix @ (query_vec / np.linalg.norm(query_vec))
    best = int(similarities.argmax())
    return sources[best], float(similarities[best])
