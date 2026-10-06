import pytest

from src.retrieval import versions
from src.routing import classifier, corpus_probe, router


@pytest.fixture
def votes(monkeypatch):
    """Fake classifier and probe. Tests edit the dict to choose each vote."""
    votes = {"classifier": (False, 0.54), "probe": ("ingested/batch/quokka.txt", 0.75)}
    monkeypatch.setattr(router, "CORPUS_PROBE_THRESHOLD", 0.55)
    monkeypatch.setattr(router, "CORPUS_PROBE_FLOOR", 0.45)
    monkeypatch.setattr(router, "CORPUS_PROBE_FLOOR_MAX_CONFIDENCE", 0.65)
    monkeypatch.setattr(classifier, "predict_needs_retrieval_with_confidence", lambda emb: votes["classifier"])
    monkeypatch.setattr(corpus_probe, "probe_corpus", lambda emb, vs: votes["probe"])
    return votes


def test_classifier_yes_searches_the_closest_chunks_source(votes):
    """Verify a 'retrieve' vote ignores the probe threshold, but the closest chunk still picks the source."""
    votes["classifier"], votes["probe"] = (True, 0.61), ("cat-facts.txt", 0.50)
    route = router.decide_route([1.0, 0.0], vectorstore=None)
    assert route == router.RouteResult(True, "cat-facts.txt", 0.61, 0.50, "classifier")


def test_probe_at_threshold_overrules_no_retrieval(votes):
    """Verify similarity == threshold counts as a hit, and the closest chunk's source is searched."""
    votes["probe"] = ("ingested/batch/quokka.txt", 0.55)
    route = router.decide_route([1.0, 0.0], vectorstore=None)
    assert route == router.RouteResult(True, "ingested/batch/quokka.txt", 0.54, 0.55, "probe")


def test_distant_probe_keeps_no_retrieval(votes):
    """Verify a low probe similarity answers without retrieval."""
    votes["probe"] = ("pydantic.llms-full.txt", 0.43)
    route = router.decide_route([1.0, 0.0], vectorstore=None)
    assert route == router.RouteResult(False, "none", 0.54, 0.43, "no_retrieval")


def test_empty_index_searches_every_source(votes):
    """Verify a 'retrieve' vote on an empty index falls back to 'none' (all sources) instead of failing."""
    votes["classifier"], votes["probe"] = (True, 0.70), (None, 0.0)
    route = router.decide_route([1.0, 0.0], vectorstore=None)
    assert route == router.RouteResult(True, "none", 0.70, 0.0, "classifier")


def test_a_named_release_routes_to_its_source(votes, monkeypatch):
    """Verify a question naming an indexed release goes to that release's source, even against both votes."""
    votes["probe"] = ("pydantic.llms-full.txt", 0.80)
    monkeypatch.setattr(versions, "release_source", lambda vs, query: "ingested/batch/releases.md")
    route = router.decide_route([1.0, 0.0], vectorstore=None, query="What changed in v2.51.0?")
    assert route == router.RouteResult(True, "ingested/batch/releases.md", 0.54, 0.80, "version")


def test_unsure_vote_without_a_close_chunk_answers_directly(votes):
    """Verify an unsure 'retrieve' vote is dropped when no chunk reaches the floor (nothing in the corpus covers it)."""
    votes["classifier"], votes["probe"] = (True, 0.55), ("cat-facts.txt", 0.33)
    route = router.decide_route([1.0, 0.0], vectorstore=None)
    assert route == router.RouteResult(False, "none", 0.55, 0.33, "floor")


def test_sure_vote_is_not_floored(votes):
    """Verify a confident 'retrieve' vote stands even with a distant closest chunk (the benchmark's vote-count case)."""
    votes["classifier"], votes["probe"] = (True, 0.75), ("fictional_text.txt", 0.40)
    route = router.decide_route([1.0, 0.0], vectorstore=None)
    assert route == router.RouteResult(True, "fictional_text.txt", 0.75, 0.40, "classifier")
