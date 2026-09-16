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
