import numpy as np
from src.logging_config import setup_logging

logger = setup_logging(__name__)


def score_groundedness(answer_embedding: list[float], context_embedding: list[float]) -> float:
    """Compute cosine similarity between answer embedding and context embedding.
    
    Args:
        answer_embedding: Vector embedding of the generated answer.
        context_embedding: Vector embedding of the retrieved context text.
        
    Returns:
        float: Cosine similarity score in range [-1.0, 1.0].
    """
    a = np.array(answer_embedding)
    c = np.array(context_embedding)

    norm_a = np.linalg.norm(a)
    norm_c = np.linalg.norm(c)

    if norm_a == 0 or norm_c == 0:
        logger.warning("[Groundedness]: Zero vector encountered in groundedness check.")
        return 0.0

    similarity = np.dot(a, c) / (norm_a * norm_c)
    return float(similarity)


def chunk_similarities(answer_embedding: list[float], chunk_embeddings: list[list[float]]) -> list[float]:
    """Cosine similarity of the answer to each retrieved chunk, in chunk order.

    The answer-context similarity is the best of these. Scoring chunks one by one replaces one embedding of the
    joined context: all-MiniLM-L6-v2 reads only its first 256 word pieces (about 1,000 characters), so a context
    of 4-8 chunks was scored on its first one or two.
    """
    return [score_groundedness(answer_embedding, chunk) for chunk in chunk_embeddings]
