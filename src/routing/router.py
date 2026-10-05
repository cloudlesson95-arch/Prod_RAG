from dataclasses import dataclass

from src.config import CORPUS_PROBE_THRESHOLD
from src.routing import classifier, clustering, corpus_probe
from src.logging_config import setup_logging

logger = setup_logging(__name__)


@dataclass
class RouteResult:
    """One classical routing decision, shared by /query, the MCP route_query tool and the routing checks."""
    needs_retrieval: bool
    source: str                     # "none" when the query is answered without retrieval
    confidence: float               # the classifier's raw probability for its own decision (uncalibrated)
    probe_similarity: float | None  # set only when the corpus probe ran
    reason: str                     # "classifier", "probe" or "no_retrieval"


def decide_route(query_embedding, vectorstore) -> RouteResult:
    """Decide whether a query needs retrieval and, if so, which source to search.

    The classifier votes first. If it says no, the corpus probe can overrule it: the classifier
    never sees the corpus, so a close enough chunk means some indexed document covers the query.
    The nearest source centroid then picks the source (it beat the probe chunk's source in Phase 6).
    """
    needs_retrieval, confidence = classifier.predict_needs_retrieval_with_confidence(query_embedding)
    logger.info(f"[Classical Router]: Retrieval decision={needs_retrieval} (Confidence: {confidence:.2f})")

    probe_similarity = None
    reason = "classifier"
    if not needs_retrieval:
        probe_source, probe_similarity = corpus_probe.probe_corpus(query_embedding, vectorstore)
        if probe_similarity < CORPUS_PROBE_THRESHOLD:
            logger.info(f"[Corpus Probe]: Closest chunk at {probe_similarity:.2f} < {CORPUS_PROBE_THRESHOLD:.2f}")
            logger.info("[Classical Router]: No retrieval needed")
            return RouteResult(False, "none", confidence, probe_similarity, "no_retrieval")
        reason = "probe"
        logger.info(f"[Corpus Probe]: Closest chunk ('{probe_source}') at {probe_similarity:.2f} >= "
                    f"{CORPUS_PROBE_THRESHOLD:.2f}; retrieving anyway")

    source = clustering.predict_source(query_embedding)
    logger.info(f"[Classical Router]: Selected source '{source}' (Nearest Centroid)")
    return RouteResult(True, source, confidence, probe_similarity, reason)
