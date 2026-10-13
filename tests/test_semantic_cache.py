import pytest

from src.retrieval import semantic_cache

QUESTION = "What is a group of cats called?"


@pytest.fixture(autouse=True)
def cache_file(monkeypatch, tmp_path):
    """Every test gets its own empty cache file, never the real LOCAL_DIR/s_cache."""
    monkeypatch.setattr(semantic_cache, "SEMANTIC_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(semantic_cache, "CACHE_FILE_PATH", str(tmp_path / "semantic_cache.joblib"))


def test_a_cached_answer_comes_back_with_its_details():
    """Verify an entry stored with details is found again, with the same answer and details."""
    details = {"source": "cat-facts.txt", "route_reason": "classifier", "router_confidence": 0.9,
               "probe_similarity": 0.62, "groundedness_score": 1.0,
               "passages": [{"source": "cat-facts.txt", "text": "A group of cats is called a clowder.", "similarity": 1.0}]}
    semantic_cache.add_to_cache(QUESTION, [1.0, 0.0], "A clowder.", details)

    entry, similarity = semantic_cache.check_cache([1.0, 0.0])

    assert (entry["answer"], entry["details"], similarity) == ("A clowder.", details, 1.0)


def test_a_different_question_misses():
    """Verify a question unlike every cached one finds no entry."""
    semantic_cache.add_to_cache(QUESTION, [1.0, 0.0], "A clowder.")

    assert semantic_cache.check_cache([0.0, 1.0]) == (None, 0.0)
