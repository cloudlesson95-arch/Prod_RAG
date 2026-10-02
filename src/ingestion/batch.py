import os
from dataclasses import dataclass, field

from src.config import INGESTED_DATA_DIR
from src.core.indexing import sync_and_retrain
from src.ingestion.errors import IngestError
from src.ingestion.extract import extract_upload_text, safe_upload_name
from src.storage.state_sync import (
    StateReadOnlyError, initialize_state, read_local_version, read_only_reason, state_write,
)
from src.logging_config import setup_logging

logger = setup_logging(__name__)

BATCH_DIR = os.path.join(INGESTED_DATA_DIR, "batch")


@dataclass
class BatchResult:
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (inbox file name, reason)
    changed_sources: set[str] = field(default_factory=set)
    state_version: str | None = None
    published: bool = False


def ingest_batch(inbox_dir: str) -> BatchResult:
    """Index every .txt, .md and .pdf file in inbox_dir into the shared corpus and publish one snapshot.

    Starts from the latest snapshot, extracts every file before any write, and publishes nothing
    when no file is new or changed. Files are stored flat under DATA_DIR/ingested/batch/.

    Raises:
        FileNotFoundError: inbox_dir doesn't exist.
        StateReadOnlyError: The latest snapshot couldn't be restored, so nothing may be published.
        SnapshotConflict: Another writer published while this batch ran.
    """
    if not os.path.isdir(inbox_dir):
        raise FileNotFoundError(f"Inbox folder '{inbox_dir}' does not exist")

    initialize_state()
    reason = read_only_reason()
    if reason:
        raise StateReadOnlyError(reason)

    result = BatchResult()
    to_write: dict[str, str] = {}
    seen: set[str] = set()
    for entry in sorted(os.listdir(inbox_dir)):
        path = os.path.join(inbox_dir, entry)
        if not os.path.isfile(path):
            continue
        try:
            name = safe_upload_name(entry)
            if name in seen:
                raise IngestError(f"Another inbox file is already stored as '{name}'")
            with open(path, "rb") as f:
                text = extract_upload_text(entry, f.read())
        except IngestError as e:
            result.failed.append((entry, str(e)))
            logger.warning(f"[Batch] Skipping '{entry}': {e}")
            continue
        seen.add(name)

        existing = _read_stored_text(os.path.join(BATCH_DIR, name))
        if existing == text:
            result.unchanged.append(name)
        else:
            (result.added if existing is None else result.modified).append(name)
            to_write[name] = text

    if not to_write:
        logger.info("[Batch] No new or changed documents; nothing to publish")
        return result

    with state_write():
        os.makedirs(BATCH_DIR, exist_ok=True)
        for name, text in to_write.items():
            with open(os.path.join(BATCH_DIR, name), "w", encoding="utf-8", newline="") as f:
                f.write(text)
        result.changed_sources = sync_and_retrain()

    result.state_version = read_local_version()
    result.published = True
    return result


def _read_stored_text(path: str) -> str | None:
    """Return a stored batch file's exact text, or None if it doesn't exist."""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()
