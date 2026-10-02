from src.core.vectorstore import sync_incremental_index
from src.routing.clustering import train_clustering
from src.routing.classifier import train_classifier
from src.storage.state_sync import state_write
from src.logging_config import setup_logging

logger = setup_logging(__name__)


def sync_and_retrain(force_rebuild: bool = False) -> set[str]:
    """Sync the index with DATA_DIR and retrain the routing models, without publishing.

    The caller must already be inside state_write(). Its lock isn't reentrant,
    so code inside a write block calls this, never reindex().

    Returns:
        set[str]: Filenames that were added, modified or deleted.
    """
    logger.info(f"Running document index sync (rebuild={force_rebuild})...")
    _, changed_sources = sync_incremental_index(force_rebuild=force_rebuild)

    logger.info("Updating classical ML routing models...")
    train_clustering(changed_sources=changed_sources, force_rebuild=force_rebuild)
    train_classifier()
    return changed_sources


def reindex(force_rebuild: bool = False) -> set[str]:
    """Sync the index with DATA_DIR, retrain the routing models and publish the new state.

    Returns:
        set[str]: Filenames that were added, modified or deleted.
    """
    with state_write():
        return sync_and_retrain(force_rebuild=force_rebuild)
