import hashlib
import os
from dataclasses import dataclass, field

from src.config import DATA_DIR, EVAL_LLM_MODEL, INGESTED_DATA_DIR
from src.core.indexing import sync_and_retrain
from src.core.utils import create_llm
from src.core.vectorstore import compute_file_hash
from src.ingestion.errors import IngestError
from src.ingestion.extract import extract_upload_text, safe_upload_name
from src.ingestion.questions import generate_questions
from src.storage.question_store import replace_questions, sources_missing_questions
from src.storage.state_sync import (
    StateReadOnlyError, initialize_state, read_local_version, read_only_reason, state_write,
)
from src.logging_config import setup_logging

logger = setup_logging(__name__)

BATCH_DIR = os.path.join(INGESTED_DATA_DIR, "batch")
BATCH_SOURCE_PREFIX = "ingested/batch/"  # BATCH_DIR relative to DATA_DIR, the way the registry and chunks name sources


@dataclass
class BatchResult:
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (inbox file name, reason)
    changed_sources: set[str] = field(default_factory=set)
    state_version: str | None = None
    published: bool = False
    questions_generated: int = 0
    question_sources: list[str] = field(default_factory=list)  # documents that got new questions in this batch


def ingest_batch(inbox_dir: str, generate: bool = True, llm=None) -> BatchResult:
    """Index every .txt, .md and .pdf file in inbox_dir into the shared corpus and publish one snapshot.

    Starts from the latest snapshot and extracts every file before any write. With generate, the LLM also
    writes questions for each new or changed file and for indexed documents that have none yet (seed
    documents included); they train the retrieval classifier in the same publish. Publishes nothing when
    no file is new or changed and no questions were written. Files are stored flat under DATA_DIR/ingested/batch/.

    Args:
        generate: False skips the LLM entirely (offline runs); a later batch fills the questions in.
        llm: The chat model that writes questions; created from EVAL_LLM_MODEL when needed.

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

    planned = _generate_questions(to_write, llm) if generate else {}
    if not to_write and not planned:
        logger.info("[Batch] No new or changed documents and no questions to add; nothing to publish")
        return result

    with state_write():
        os.makedirs(BATCH_DIR, exist_ok=True)
        for name, text in to_write.items():
            with open(os.path.join(BATCH_DIR, name), "w", encoding="utf-8", newline="") as f:
                f.write(text)
        for source, (file_hash, items) in planned.items():
            replace_questions(source, file_hash, items)
        result.changed_sources = sync_and_retrain()  # retrains the classifier on the questions stored above

    result.question_sources = sorted(planned)
    result.questions_generated = sum(len(items) for _, items in planned.values())
    result.state_version = read_local_version()
    result.published = True
    return result


def _generate_questions(to_write: dict[str, str], llm=None) -> dict[str, tuple[str, list[dict]]]:
    """Have the LLM write questions for this batch's new or changed files and for indexed documents that have none.

    Runs before the write lock: LLM calls are slow and can fail, and a failure must not leave half a write.
    A document that gets no questions is still ingested; a later batch fills it in.

    Returns:
        dict: source -> (hash of the file version the questions belong to, non-empty list of question dicts)
    """
    texts = {BATCH_SOURCE_PREFIX + name: text for name, text in to_write.items()}
    # Written with newline="" below, so the file's bytes, and the registry's hash of them, are text.encode("utf-8")
    hashes = {source: hashlib.sha256(text.encode("utf-8")).hexdigest() for source, text in texts.items()}
    for source in sources_missing_questions():
        if source in texts:
            continue
        path = os.path.join(DATA_DIR, source)
        if not os.path.exists(path):
            logger.warning(f"[Batch] '{source}' is registered but missing from DATA_DIR; no questions for it")
            continue
        with open(path, "r", encoding="utf-8") as f:
            texts[source] = f.read()
        hashes[source] = compute_file_hash(path)
    if not texts:
        return {}

    try:
        llm = llm or create_llm(EVAL_LLM_MODEL)
    except Exception as e:  # no key or provider unreachable: ingest without questions this time
        logger.warning(f"[Batch] No LLM available, so no questions this time: {e}")
        return {}

    planned = {}
    for source, text in texts.items():
        items = generate_questions(text, llm)
        logger.info(f"[Batch] {len(items)} questions for '{source}'")
        if items:
            planned[source] = (hashes[source], items)
    return planned


def _read_stored_text(path: str) -> str | None:
    """Return a stored batch file's exact text, or None if it doesn't exist."""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()
