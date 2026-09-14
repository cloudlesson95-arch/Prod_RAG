import os
import joblib
import shutil
import time
import numpy as np

from src.logging_config import setup_logging
from src.config import SEMANTIC_CACHE_DIR, CACHE_SIMILARITY_THRESHOLD

logger = setup_logging(__name__)
CACHE_FILE_PATH = os.path.join(SEMANTIC_CACHE_DIR, "semantic_cache.joblib")

def load_cache() -> list:    
    """Load cached query/answer records from disk."""
    if not os.path.exists(SEMANTIC_CACHE_DIR) or not os.path.exists(CACHE_FILE_PATH):
        logger.debug("No semantic cache file found. Returning empty list.")
        return []
    try:
        return joblib.load(CACHE_FILE_PATH)
    except Exception as e:
        logger.error(f"Failed to load semantic cache: {e}")
        return []

def save_cache(records: list):
    """Persist cache records list to disk."""
    os.makedirs(SEMANTIC_CACHE_DIR, exist_ok=True)
    joblib.dump(records, CACHE_FILE_PATH)
    logger.debug(f"Saved {len(records)} entries to semantic cache.") 

def check_cache(query_embedding):
    """Check if query_embedding has a high similarity match in the cache.
    
    Returns:
        tuple: (hit: bool, answer: str | None, max_similarity: float)
    """
    records  = load_cache()
    if not records:
        return False, None, 0.0

    query_vec = np.array(query_embedding)
    best_match = None
    max_sim = -1.0

    for record in records:
        cached_vec = np.array(record["vector"])
        sim = float(np.dot(query_embedding, cached_vec))
        if sim > max_sim:
            max_sim = sim
            best_match = record
            
    if max_sim >= CACHE_SIMILARITY_THRESHOLD and best_match is not None:
        return True, best_match["answer"], max_sim
    else:
        return False, None, max_sim

def add_to_cache(query: str, query_embedding, answer: str):
    """Add a new query-answer pair to the semantic cache."""
    records = load_cache()
    entry = {
        "query": query,
        "vector": query_embedding, 
        "answer": answer,
        "timestamp": time.time()
    }
    records.append(entry)
    save_cache(records)
    logger.info(f"[Semantic Cache]: Cached new answer for query: '{query}'")

def remove_cache_entry(query: str):
    """Evict a specific query from the semantic cache"""
    records = load_cache()
    if not records:
        return
        
    new_records = [r for r in records if r.get("query") != query]
    if len(new_records) < len(records):
        save_cache(new_records)
        logger.info(f"[Semantic Cache]: Evicted bad cache entry for query: '{query}'")

def clear_cache():
    """Clear all semantic cache entries from disk."""
    logger.info(f"Clearing semantic caches at: {SEMANTIC_CACHE_DIR}")
    if os.path.exists(SEMANTIC_CACHE_DIR):
        shutil.rmtree(SEMANTIC_CACHE_DIR)
        logger.info("Semantic cache cleared successfully.")
