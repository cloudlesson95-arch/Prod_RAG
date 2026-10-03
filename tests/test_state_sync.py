import tarfile
from pathlib import Path
from importlib.metadata import PackageNotFoundError

import pytest
from langchain_chroma import Chroma
from langchain_core.embeddings import DeterministicFakeEmbedding

from src.storage import state_sync
from src.storage.state_store import SnapshotConflict
from src.storage.state_sync import (
    pack_state, unpack_state, seed_from_image, read_local_version, write_local_version,
    initialize_state, state_write, read_only_reason, StateReadOnlyError,
)


def make_state(root: Path) -> tuple[str, str]:
    """Create a small data dir + local dir with every kind of item the snapshot cares about."""
    data, local = root / "data", root / ".local"
    (data / "ingested").mkdir(parents=True)
    (data / "cat-facts.txt").write_text("cats purr")
    (data / "ingested" / "new.txt").write_text("fresh doc")
    (local / "clusters").mkdir(parents=True)
    (local / "clusters" / "model.joblib").write_bytes(b"model")
    (local / "chroma_db").mkdir()
    (local / "chroma_db" / "chroma.sqlite3").write_bytes(b"chroma")
    (local / "rag.db").write_bytes(b"sqlite")
    (local / "s_cache").mkdir()
    (local / "s_cache" / "semantic_cache.joblib").write_bytes(b"cache")
    (local / ".snapshot_version").write_text("v7")
    return str(data), str(local)


def test_pack_unpack_round_trip(tmp_path):
    """Verify data and snapshot items survive a round trip; cache and version file do not travel."""
    src_data, src_local = make_state(tmp_path / "src")
    archive = str(tmp_path / "state.tar.gz")
    pack_state(archive, data_dir=src_data, local_dir=src_local)

    dst_data, dst_local = tmp_path / "dst" / "data", tmp_path / "dst" / ".local"
    unpack_state(archive, data_dir=str(dst_data), local_dir=str(dst_local))

    assert (dst_data / "ingested" / "new.txt").read_text() == "fresh doc"
    assert (dst_local / "clusters" / "model.joblib").read_bytes() == b"model"
    assert (dst_local / "rag.db").read_bytes() == b"sqlite"
    assert not (dst_local / "s_cache").exists()
    assert read_local_version(str(dst_local)) is None

    write_local_version("v8", str(dst_local))
    assert read_local_version(str(dst_local)) == "v8"


def test_unpack_replaces_stale_state_but_keeps_cache(tmp_path):
    """Verify the snapshot fully replaces snapshot items while per-instance files stay."""
    src_data, src_local = make_state(tmp_path / "src")
    archive = str(tmp_path / "state.tar.gz")
    pack_state(archive, data_dir=src_data, local_dir=src_local)

    dst_data, dst_local = make_state(tmp_path / "dst")
    (Path(dst_data) / "stale.txt").write_text("old")
    unpack_state(archive, data_dir=dst_data, local_dir=dst_local)

    assert not (Path(dst_data) / "stale.txt").exists()
    assert (Path(dst_local) / "s_cache" / "semantic_cache.joblib").exists()


def test_seed_from_image_fills_empty_targets(tmp_path):
    """Verify seeding copies into empty targets (even a pre-created LOCAL_DIR) exactly once."""
    seed_data, seed_local = make_state(tmp_path / "image")
    data, local = tmp_path / "work" / "data", tmp_path / "work" / ".local"
    local.mkdir(parents=True)
    (local / "rag.db").write_bytes(b"")  # e.g. created early by doc_registry's os.makedirs + connect

    assert seed_from_image(str(data), str(local), seed_data, seed_local) is True
    assert (data / "cat-facts.txt").exists()
    assert (local / "chroma_db" / "chroma.sqlite3").exists()
    assert not (local / "s_cache").exists()
    assert not (local / ".snapshot_version").exists()

    assert seed_from_image(str(data), str(local), seed_data, seed_local) is False


def test_seed_from_image_is_noop_when_working_dirs_are_the_seed(tmp_path):
    """Verify local dev (working dirs == seed dirs) never copies anything."""
    seed_data, seed_local = make_state(tmp_path / "repo")
    assert seed_from_image(seed_data, seed_local, seed_data, seed_local) is False


def test_chroma_survives_round_trip_while_client_open(tmp_path):
    """Verify a Chroma dir packed while its client is still open reopens with the same content."""
    embeddings = DeterministicFakeEmbedding(size=32)
    src_data, src_local = tmp_path / "src" / "data", tmp_path / "src" / ".local"
    src_data.mkdir(parents=True)
    texts = [f"document number {i} about cats" for i in range(50)]
    original = Chroma(persist_directory=str(src_local / "chroma_db"), embedding_function=embeddings)
    original.add_texts(texts, ids=[f"doc_{i}" for i in range(50)])

    archive = str(tmp_path / "state.tar.gz")
    pack_state(archive, data_dir=str(src_data), local_dir=str(src_local))  # client still open, as in production

    dst_local = tmp_path / "dst" / ".local"
    unpack_state(archive, data_dir=str(tmp_path / "dst" / "data"), local_dir=str(dst_local))
    restored = Chroma(persist_directory=str(dst_local / "chroma_db"), embedding_function=embeddings)

    query = "document number 7 about cats"
    assert restored._collection.count() == 50
    assert [d.page_content for d in restored.similarity_search(query, k=3)] == \
           [d.page_content for d in original.similarity_search(query, k=3)]


@pytest.fixture
def state_env(tmp_path, monkeypatch, fake_store):
    """Point state_sync at tmp seed/working dirs and the in-memory store."""
    seed_data, seed_local = make_state(tmp_path / "image")
    data, local = tmp_path / "work" / "data", tmp_path / "work" / ".local"
    monkeypatch.setattr(state_sync, "SEED_DATA_DIR", seed_data)
    monkeypatch.setattr(state_sync, "SEED_LOCAL_DIR", seed_local)
    monkeypatch.setattr(state_sync, "DATA_DIR", str(data))
    monkeypatch.setattr(state_sync, "LOCAL_DIR", str(local))
    monkeypatch.setattr(state_sync, "get_state_store", lambda: fake_store)
    monkeypatch.setattr(state_sync, "_read_only_reason", None)
    monkeypatch.setattr(state_sync, "lock_mismatches", lambda: [])
    return data, local, fake_store


def test_initialize_first_boot_seeds_and_publishes(state_env):
    """Verify an empty store gets the image seed as its first snapshot."""
    data, local, store = state_env
    initialize_state()

    assert (data / "cat-facts.txt").exists()
    assert store.uploads == 1
    assert read_local_version(str(local)) == store.version
    assert read_only_reason() is None


def test_initialize_restores_existing_snapshot(state_env, tmp_path):
    """Verify an existing snapshot wins over the image seed and nothing is re-uploaded."""
    data, local, store = state_env
    other_data, other_local = make_state(tmp_path / "other")
    (Path(other_data) / "ingested" / "extra.txt").write_text("from snapshot")
    archive = str(tmp_path / "existing.tar.gz")
    pack_state(archive, data_dir=other_data, local_dir=other_local)
    version = store.upload(archive, expected_version=None)

    initialize_state()

    assert (data / "ingested" / "extra.txt").read_text() == "from snapshot"
    assert read_local_version(str(local)) == version
    assert store.uploads == 1


def test_initialize_goes_read_only_when_store_fails(state_env, monkeypatch):
    """Verify a store outage serves the seed and refuses writes instead of crashing."""
    data, local, store = state_env

    def unreachable(*args, **kwargs):
        raise ConnectionError("store unreachable")
    monkeypatch.setattr(store, "download", unreachable)

    initialize_state()

    assert (data / "cat-facts.txt").exists()
    assert "unavailable" in read_only_reason()
    with pytest.raises(StateReadOnlyError):
        with state_write():
            pass
    assert store.uploads == 0


def test_state_write_publishes_new_snapshot(state_env, tmp_path):
    """Verify a successful write uploads a snapshot containing the change."""
    data, local, store = state_env
    initialize_state()

    with state_write():
        (data / "ingested" / "doc.txt").write_text("hello")

    assert store.version == "v2" == read_local_version(str(local))
    archive = tmp_path / "published.tar.gz"
    store.download(str(archive))
    with tarfile.open(archive) as tar:
        assert "data/ingested/doc.txt" in tar.getnames()


def test_state_write_on_stale_copy_conflicts_before_running_body(state_env):
    """Verify a stale copy is rejected before any local change, then stays read-only."""
    data, local, store = state_env
    initialize_state()
    store.version = "published-by-another-instance"

    ran = False
    with pytest.raises(SnapshotConflict):
        with state_write():
            ran = True
    assert not ran

    with pytest.raises(StateReadOnlyError):
        with state_write():
            pass


def test_state_write_failure_in_body_skips_upload_and_goes_read_only(state_env):
    """Verify a failed write never publishes half-changed state."""
    data, local, store = state_env
    initialize_state()

    with pytest.raises(RuntimeError):
        with state_write():
            raise RuntimeError("embedding failed")

    assert store.uploads == 1
    assert read_only_reason() is not None


def test_state_write_upload_race_goes_read_only(state_env):
    """Verify losing the race between pre-check and upload is a conflict, not an overwrite."""
    data, local, store = state_env
    initialize_state()

    with pytest.raises(SnapshotConflict):
        with state_write():
            store.version = "racer"  # another instance publishes mid-write

    assert store.version == "racer"
    assert read_only_reason() is not None


def test_local_backend_writes_without_snapshots(state_env, monkeypatch):
    """Verify STATE_BACKEND=local runs the write block and publishes nothing."""
    data, local, store = state_env
    monkeypatch.setattr(state_sync, "get_state_store", lambda: None)
    initialize_state()

    with state_write():
        (data / "ingested" / "doc.txt").write_text("hello")

    assert (data / "ingested" / "doc.txt").exists()
    assert store.uploads == 0
    assert read_local_version(str(local)) is None


def test_remote_backend_rejects_seed_dirs_as_working_dirs(state_env, monkeypatch):
    """Verify a remote backend refuses to use the seed dirs as its working copy."""
    monkeypatch.setattr(state_sync, "DATA_DIR", state_sync.SEED_DATA_DIR)
    with pytest.raises(ValueError):
        initialize_state()


def test_seed_from_image_ignores_leftovers_in_data_dir(tmp_path):
    """Verify leftover files in DATA_DIR don't stop the corpus from being seeded with the index."""
    seed_data, seed_local = make_state(tmp_path / "image")
    data, local = tmp_path / "work" / "data", tmp_path / "work" / ".local"
    (data / "ingested").mkdir(parents=True)
    (data / "ingested" / "leftover.txt").write_text("from an earlier run")

    assert seed_from_image(str(data), str(local), seed_data, seed_local) is True
    assert (data / "cat-facts.txt").exists()
    assert (data / "ingested" / "leftover.txt").exists()


def test_lock_mismatches_compares_installed_versions_with_pins(tmp_path, monkeypatch):
    """Verify pins are read from name==version lines (markers and comments ignored) and compared exactly."""
    lock = tmp_path / "requirements.txt"
    lock.write_text(
        "numpy==2.5.3\n"
        "    # via scikit-learn\n"
        "scikit-learn==1.9.1\n"
        "torch==2.14.0+cpu ; sys_platform != 'darwin'\n"
    )
    installed = {"numpy": "2.5.3", "scikit-learn": "1.7.2"}

    def fake_version(name):
        if name not in installed:
            raise PackageNotFoundError(name)
        return installed[name]

    monkeypatch.setattr(state_sync, "version", fake_version)

    assert state_sync.lock_mismatches(str(lock), ("numpy", "scikit-learn", "chromadb")) == [
        "scikit-learn 1.7.2 (lock: 1.9.1)",
        "chromadb not installed (lock: not pinned)",
    ]


def test_state_write_refuses_to_publish_from_unsynced_environment(state_env, monkeypatch):
    """Verify a version mismatch stops the write before the body runs, without making the instance read-only."""
    data, local, store = state_env
    initialize_state()
    monkeypatch.setattr(state_sync, "lock_mismatches", lambda: ["scikit-learn 1.7.2 (lock: 1.9.1)"])

    ran = False
    with pytest.raises(StateReadOnlyError, match="scikit-learn 1.7.2"):
        with state_write():
            ran = True

    assert not ran
    assert store.uploads == 1  # only the first-boot seed
    assert read_only_reason() is None


def test_local_backend_skips_the_lock_check(state_env, monkeypatch):
    """Verify local development (no remote store) never needs a synced environment."""
    data, local, store = state_env
    monkeypatch.setattr(state_sync, "get_state_store", lambda: None)
    initialize_state()  # seeds the empty working dirs, as at app startup

    def must_not_run():
        raise AssertionError("lock check ran for the local backend")

    monkeypatch.setattr(state_sync, "lock_mismatches", must_not_run)

    with state_write():
        (data / "ingested" / "doc.txt").write_text("hello")
    assert (data / "ingested" / "doc.txt").exists()
    assert store.uploads == 0
