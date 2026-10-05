from dataclasses import dataclass

from src.config import CORPUS_PROBE_THRESHOLD
from src.routing import classifier, corpus_probe
from src.logging_config import setup_logging

logger = setup_logging(__name__)


@dataclass
class RouteResult:
    """One classical routing decision, shared by /query, the MCP route_query tool and the routing checks."""
    needs_retrieval: bool
    source: str              # "none" when the query is answered without retrieval
    confidence: float        # the classifier's raw probability for its own decision (uncalibrated)
    probe_similarity: float  # cosine similarity of the closest chunk (0.0 for an empty index)
    reason: str              # "classifier", "probe" or "no_retrieval"


def decide_route(query_embedding, vectorstore) -> RouteResult:
    """Decide whether a query needs retrieval and, if so, which source to search.

    The classifier votes first. The corpus probe then finds the closest chunk by exact search: if the
    classifier said no, a close enough chunk overrules it (the classifier never sees the corpus).
    The closest chunk's source is the one to search. Nearest centroids lost to it on the routing fixture
    (20 vs. 25 of 25): a broad source's centroid pulls in every generic question about its topic.
    """
    needs_retrieval, confidence = classifier.predict_needs_retrieval_with_confidence(query_embedding)
    logger.info(f"[Classical Router]: Retrieval decision={needs_retrieval} (Confidence: {confidence:.2f})")

    probe_source, probe_similarity = corpus_probe.probe_corpus(query_embedding, vectorstore)
    reason = "classifier"
    if not needs_retrieval:
        if probe_similarity < CORPUS_PROBE_THRESHOLD:
            logger.info(f"[Corpus Probe]: Closest chunk at {probe_similarity:.2f} < {CORPUS_PROBE_THRESHOLD:.2f}")
            logger.info("[Classical Router]: No retrieval needed")
            return RouteResult(False, "none", confidence, probe_similarity, "no_retrieval")
        reason = "probe"
        logger.info(f"[Corpus Probe]: Closest chunk at {probe_similarity:.2f} >= {CORPUS_PROBE_THRESHOLD:.2f}; "
                    "retrieving anyway")

    source = probe_source or "none"  # "none" searches every source; only reachable with an empty index
    logger.info(f"[Classical Router]: Selected source '{source}' (closest chunk at {probe_similarity:.2f})")
    return RouteResult(True, source, confidence, probe_similarity, reason)
