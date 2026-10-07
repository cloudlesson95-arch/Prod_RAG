"""Aggregates behind the dashboard's /stats endpoints: pure functions over event records and registry rows."""
from collections import Counter
from statistics import mean

from src.config import LIVE_EVAL_CLIENT
from src.monitoring.drift import population_stability_index

MIN_QUERIES_FOR_PSI = 30  # below this, one question more or less can swing PSI across bands


def psi_band(psi: float) -> str:
    """The usual reading of PSI: below 0.1 stable, 0.1 up to 0.25 moderate drift, 0.25 or more significant drift."""
    if psi < 0.1:
        return "stable"
    return "moderate" if psi < 0.25 else "significant"


def routing_stats(events: list[dict], baseline: dict[str, int], days: int) -> dict:
    """Users' routed queries per source and reason, and how far that mix drifted from the baseline.

    live-eval's requests and semantic cache hits are counted but kept out of the mix: the first are the benchmark,
    not users, and a cache hit has no routing decision.
    """
    user = [e for e in events if e.get("origin") != LIVE_EVAL_CLIENT]
    routed = [e for e in user if not e.get("cache_hit")]
    by_source = Counter(e.get("source") for e in routed)
    scores = [e["groundedness_score"] for e in routed if e.get("groundedness_score") is not None]
    psi = population_stability_index(baseline, by_source) if len(routed) >= MIN_QUERIES_FOR_PSI else None
    return {
        "days": days,
        "queries": len(user),
        "cache_hits": len(user) - len(routed),
        "live_eval_queries": len(events) - len(user),
        "by_source": dict(by_source.most_common()),
        "by_reason": dict(Counter(e.get("route_reason") for e in routed).most_common()),
        "mean_groundedness": mean(scores) if scores else None,
        "baseline": dict(Counter(baseline).most_common()),
        "psi": psi,
        "psi_band": psi_band(psi) if psi is not None else None,
        "min_queries_for_psi": MIN_QUERIES_FOR_PSI,
    }


def corpus_stats(documents: dict[str, dict], questions: list[dict], state_version: str | None) -> dict:
    """The indexed documents with their chunk count, size, ingest time and number of generated questions."""
    per_source = Counter(q["source"] for q in questions)
    rows = [{"filename": name, "chunk_count": info["chunk_count"], "file_size": info["file_size"],
             "ingested_at": info["ingested_at"], "questions": per_source[name]}
            for name, info in sorted(documents.items())]
    return {"state_version": state_version, "total_chunks": sum(row["chunk_count"] for row in rows), "documents": rows}
