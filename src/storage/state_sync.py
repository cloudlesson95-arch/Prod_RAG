import os
import shutil
import tarfile
import tempfile
import threading
from contextlib import contextmanager

from src.config import DATA_DIR, LOCAL_DIR, SEED_DATA_DIR, SEED_LOCAL_DIR
from src.logging_config import setup_logging
from src.storage.state_store import StateStore, SnapshotConflict, get_state_store

logger = setup_logging(__name__)

# Items under LOCAL_DIR that belong to the snapshot. Everything else there
# (s_cache/, the version file) is per-instance and never leaves the machine.
SNAPSHOT_LOCAL_ITEMS = ("chroma_db", "clusters", "rag.db")
SNAPSHOT_VERSION_FILE = ".snapshot_version"


def pack_state(archive_path: str, data_dir: str = DATA_DIR, local_dir: str = LOCAL_DIR) -> None:
    """Write data_dir and the snapshot items of local_dir into one tar.gz archive."""
    with tarfile.open(archive_path, "w:gz", compresslevel=6) as tar:
        tar.add(data_dir, arcname="data")
        for item in SNAPSHOT_LOCAL_ITEMS:
            path = os.path.join(local_dir, item)
            if os.path.exists(path):
                tar.add(path, arcname=f"local/{item}")
    size_mb = os.path.getsize(archive_path) / (1024 * 1024)
    logger.info(f"[State] Packed snapshot ({size_mb:.1f} MB)")


def unpack_state(archive_path: str, data_dir: str = DATA_DIR, local_dir: str = LOCAL_DIR) -> None:
    """Replace data_dir and the snapshot items of local_dir with the archive's contents.

    Only safe before any Chroma client has opened local_dir (startup or CLI).
    """
    if _same_path(data_dir, SEED_DATA_DIR) or _same_path(local_dir, SEED_LOCAL_DIR):
        raise ValueError("Refusing to unpack a snapshot over the seed dirs; set DATA_DIR and LOCAL_DIR.")

    os.makedirs(local_dir, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".restore-", dir=os.path.dirname(local_dir))
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(staging, filter="data")
        _replace(os.path.join(staging, "data"), data_dir)
        for item in SNAPSHOT_LOCAL_ITEMS:
            _replace(os.path.join(staging, "local", item), os.path.join(local_dir, item))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    logger.info(f"[State] Unpacked snapshot into '{data_dir}' and '{local_dir}'")


def seed_from_image(
    data_dir: str = DATA_DIR,
    local_dir: str = LOCAL_DIR,
    seed_data_dir: str = SEED_DATA_DIR,
    seed_local_dir: str = SEED_LOCAL_DIR,
) -> bool:
    """Copy the image's seed corpus and prebuilt index into an uninitialized working copy.

    The working copy counts as initialized once local_dir has a chroma_db. The corpus is
    seeded in the same step, so the index and the files it was built from always match.

    Returns:
        bool: True if anything was copied.
    """
    if _same_path(local_dir, seed_local_dir) or os.path.exists(os.path.join(local_dir, "chroma_db")):
        return False

    if not _same_path(data_dir, seed_data_dir):
        shutil.copytree(seed_data_dir, data_dir, dirs_exist_ok=True)
    shutil.copytree(
        seed_local_dir, local_dir, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("s_cache", SNAPSHOT_VERSION_FILE),
    )
    logger.info(f"[State] Seeded working dirs from image ('{seed_data_dir}', '{seed_local_dir}')")
    return True


def read_local_version(local_dir: str = LOCAL_DIR) -> str | None:
    """Return the snapshot version the local working copy is based on, if any."""
    path = os.path.join(local_dir, SNAPSHOT_VERSION_FILE)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip() or None


def write_local_version(version: str, local_dir: str = LOCAL_DIR) -> None:
    """Record which snapshot version the local working copy is based on."""
    os.makedirs(local_dir, exist_ok=True)
    with open(os.path.join(local_dir, SNAPSHOT_VERSION_FILE), "w", encoding="utf-8") as f:
        f.write(version)


def _replace(src: str, dest: str) -> None:
    """Move src to dest, removing whatever was at dest first."""
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    elif os.path.exists(dest):
        os.remove(dest)
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


class StateReadOnlyError(Exception):
    """Writes are disabled because this instance can't safely publish state."""


_write_lock = threading.Lock()
_read_only_reason: str | None = None


def read_only_reason() -> str | None:
    """Why writes are disabled on this instance, or None if they're allowed."""
    return _read_only_reason


def initialize_state() -> None:
    """Prepare the working copy before anything opens Chroma.

    Restores the latest snapshot, or seeds from the image and publishes it as the
    first snapshot. Store errors don't stop the app: it serves the image seed and
    refuses writes. Config errors (unknown backend, working dirs == seed dirs) raise.
    """
    global _read_only_reason
    store = get_state_store()
    if store is None:
        seed_from_image(DATA_DIR, LOCAL_DIR, SEED_DATA_DIR, SEED_LOCAL_DIR)
        return

    if _same_path(DATA_DIR, SEED_DATA_DIR) or _same_path(LOCAL_DIR, SEED_LOCAL_DIR):
        raise ValueError("A remote STATE_BACKEND needs DATA_DIR and LOCAL_DIR outside the seed dirs.")

    try:
        version = _restore_or_create(store)
        write_local_version(version, LOCAL_DIR)
    except Exception as e:
        logger.error(f"[State] Could not restore state; serving the image seed read-only: {e}", exc_info=True)
        seed_from_image(DATA_DIR, LOCAL_DIR, SEED_DATA_DIR, SEED_LOCAL_DIR)
        _read_only_reason = f"state store unavailable at startup: {e}"


def _restore_or_create(store: StateStore) -> str:
    """Restore the stored snapshot, or publish the image seed as the first one. Returns its version."""
    with tempfile.TemporaryDirectory() as tmp:
        archive = os.path.join(tmp, "state.tar.gz")
        version = store.download(archive)
        if version is not None:
            unpack_state(archive, DATA_DIR, LOCAL_DIR)
            logger.info(f"[State] Restored snapshot {version}")
            return version

        seed_from_image(DATA_DIR, LOCAL_DIR, SEED_DATA_DIR, SEED_LOCAL_DIR)
        pack_state(archive, DATA_DIR, LOCAL_DIR)
        try:
            version = store.upload(archive, expected_version=None)
            logger.info(f"[State] No snapshot yet; published the image seed as snapshot {version}")
            return version
        except SnapshotConflict:
            # Another instance published the first snapshot meanwhile: use theirs.
            version = store.download(archive)
            unpack_state(archive, DATA_DIR, LOCAL_DIR)
            logger.info(f"[State] Lost the first-snapshot race; restored snapshot {version}")
            return version


@contextmanager
def state_write():
    """Run a block that changes persistent state, then publish it as a new snapshot.

    Raises:
        StateReadOnlyError: Writes are disabled on this instance.
        SnapshotConflict: The store changed since this instance restored its copy.
    """
    global _read_only_reason
    with _write_lock:
        if _read_only_reason:
            raise StateReadOnlyError(_read_only_reason)

        store = get_state_store()
        if store is None:
            yield
            return

        base_version = read_local_version(LOCAL_DIR)
        stored_version = store.current_version()
        if stored_version != base_version:
            _read_only_reason = f"stale copy: based on {base_version}, store has {stored_version}"
            raise SnapshotConflict(_read_only_reason)

        try:
            yield
            with tempfile.TemporaryDirectory() as tmp:
                archive = os.path.join(tmp, "state.tar.gz")
                pack_state(archive, DATA_DIR, LOCAL_DIR)
                new_version = store.upload(archive, expected_version=base_version)
        except Exception as e:
            _read_only_reason = f"a write failed after changing local state: {e!r}"
            logger.error(f"[State] Write failed; read-only until restart: {e}")
            raise

        write_local_version(new_version, LOCAL_DIR)
        logger.info(f"[State] Published snapshot {new_version} (was {base_version})")
