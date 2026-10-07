import pytest

from src.monitoring.stats import MIN_QUERIES_FOR_PSI, corpus_stats, psi_band, routing_stats


def event(source="cat-facts.txt", reason="classifier", origin="user", cache_hit=False, score=None):
    return {"source": source, "route_reason": reason, "origin": origin, "cache_hit": cache_hit,
            "groundedness_score": score}


def test_routing_stats_mix_only_users_routed_queries():
    """Verify live-eval traffic and cache hits are counted but kept out of the source and reason mix."""
    events = [event(score=0.8), event(score=0.6), event(source="none", reason="no_retrieval"),
              event(source=None, reason=None, cache_hit=True), event(origin="live-eval")]

    stats = routing_stats(events, {"cat-facts.txt": 1}, days=7)

    assert (stats["queries"], stats["cache_hits"], stats["live_eval_queries"]) == (4, 1, 1)
    assert stats["by_source"] == {"cat-facts.txt": 2, "none": 1}
    assert stats["by_reason"] == {"classifier": 2, "no_retrieval": 1}
    assert stats["mean_groundedness"] == pytest.approx(0.7)


def test_psi_needs_enough_traffic():
    """Verify PSI stays empty below the minimum number of routed user queries."""
    stats = routing_stats([event()] * (MIN_QUERIES_FOR_PSI - 1), {"cat-facts.txt": 1}, days=7)
    assert (stats["psi"], stats["psi_band"]) == (None, None)


def test_psi_compares_traffic_with_the_baseline_mix():
    """Verify traffic in the baseline's proportions reads as stable, and one-sided traffic as significant drift."""
    baseline = {"cat-facts.txt": 50, "none": 50}
    same_mix = [event()] * 15 + [event(source="none", reason="no_retrieval")] * 15

    same, shifted = routing_stats(same_mix, baseline, 7), routing_stats([event()] * 30, baseline, 7)

    assert same["psi"] == pytest.approx(0.0, abs=1e-6) and same["psi_band"] == "stable"
    assert shifted["psi_band"] == "significant"


@pytest.mark.parametrize("psi, band", [(0.0, "stable"), (0.0999, "stable"), (0.1, "moderate"),
                                       (0.2499, "moderate"), (0.25, "significant")])
def test_psi_bands(psi, band):
    assert psi_band(psi) == band


def test_corpus_stats_sort_documents_and_count_their_questions():
    """Verify documents come sorted by name with their generated-question counts, and file hashes stay internal."""
    documents = {"pydantic.llms-full.txt": {"file_hash": "a", "chunk_count": 100, "file_size": 9, "ingested_at": "t1"},
                 "cat-facts.txt": {"file_hash": "b", "chunk_count": 10, "file_size": 1, "ingested_at": "t2"}}

    stats = corpus_stats(documents, [{"source": "cat-facts.txt"}] * 5, "0xETAG")

    assert [d["filename"] for d in stats["documents"]] == ["cat-facts.txt", "pydantic.llms-full.txt"]
    assert [d["questions"] for d in stats["documents"]] == [5, 0]
    assert (stats["total_chunks"], stats["state_version"]) == (110, "0xETAG")
    assert "file_hash" not in stats["documents"][0]
