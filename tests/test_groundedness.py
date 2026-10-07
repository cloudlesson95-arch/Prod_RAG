import pytest
from src.monitoring.groundedness import chunk_similarities, score_groundedness


def test_score_groundedness_identical():
    vec = [0.5, 0.5, 0.5, 0.5]
    score = score_groundedness(vec, vec)
    assert pytest.approx(score, 0.001) == 1.0


def test_score_groundedness_orthogonal():
    v1 = [1.0, 0.0]
    v2 = [0.0, 1.0]
    score = score_groundedness(v1, v2)
    assert pytest.approx(score, 0.001) == 0.0


def test_score_groundedness_opposite():
    v1 = [1.0, 2.0, 3.0]
    v2 = [-1.0, -2.0, -3.0]
    score = score_groundedness(v1, v2)
    assert pytest.approx(score, 0.001) == -1.0


def test_score_groundedness_zero_vector():
    v1 = [0.0, 0.0, 0.0]
    v2 = [1.0, 2.0, 3.0]
    score = score_groundedness(v1, v2)
    assert score == 0.0


def test_chunk_similarities_scores_each_chunk_in_order():
    scores = chunk_similarities([1.0, 0.0], [[0.0, 1.0], [1.0, 0.0], [1.0, 1.0]])
    assert scores == pytest.approx([0.0, 1.0, 0.7071], abs=0.001)


def test_chunk_similarities_without_chunks_is_empty():
    assert chunk_similarities([1.0, 0.0], []) == []
