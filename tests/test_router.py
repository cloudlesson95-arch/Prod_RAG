import pytest

from src.routing import classifier, clustering, corpus_probe, router


@pytest.fixture
def votes(monkeypatch):
    """Fake classifier, probe and centroid router. Tests edit the dict to choose each vote."""
    votes = {"classifier": (False, 0.54), "probe": ("pydantic.llms-full.txt", 0.75), "probe_calls": 0}

    def fake_probe(emb, vs):
        votes["probe_calls"] += 1
        return votes["probe"]

    monkeypatch.setattr(router, "CORPUS_PROBE_THRESHOLD", 0.55)
    monkeypatch.setattr(classifier, "predict_needs_retrieval_with_confidence", lambda emb: votes["classifier"])
    monkeypatch.setattr(corpus_probe, "probe_corpus", fake_probe)
    monkeypatch.setattr(clustering, "predict_source", lambda emb: "ingested/batch/quokka.txt")
    return votes


def test_classifier_yes_skips_the_probe(votes):
    """Verify a 'retrieve' vote goes straight to the centroid router without probing."""
    votes["classifier"] = (True, 0.61)
    route = router.decide_route([1.0, 0.0], vectorstore=None)
    assert route == router.RouteResult(True, "ingested/batch/quokka.txt", 0.61, None, "classifier")
    assert votes["probe_calls"] == 0


def test_probe_at_threshold_overrules_and_centroid_picks_source(votes):
    """Verify similarity == threshold counts as a hit, and the centroid (not the probe chunk) picks the source."""
    votes["probe"] = ("pydantic.llms-full.txt", 0.55)
    route = router.decide_route([1.0, 0.0], vectorstore=None)
    assert route == router.RouteResult(True, "ingested/batch/quokka.txt", 0.54, 0.55, "probe")


def test_distant_probe_keeps_no_retrieval(votes, monkeypatch):
    """Verify a low probe similarity answers without retrieval and never asks the centroid router."""
    votes["probe"] = ("pydantic.llms-full.txt", 0.43)
    monkeypatch.setattr(clustering, "predict_source", lambda emb: pytest.fail("centroid router ran"))
    route = router.decide_route([1.0, 0.0], vectorstore=None)
    assert route == router.RouteResult(False, "none", 0.54, 0.43, "no_retrieval")
