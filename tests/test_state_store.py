import pytest
from src.storage.state_store import get_state_store, SnapshotConflict


def check_store_contract(store, tmp_path):
    """Behavior every StateStore backend must have"""
    archive = tmp_path / "state.tar.gz"
    archive.write_bytes(b"snapshot-1")
    out = tmp_path / "downloaded"

    # Empty store
    assert store.download(str(out)) is None
    assert store.current_version() is None

    # Create-only upload succeeds once, then fails
    v1 = store.upload(str(archive), expected_version=None)
    with pytest.raises(SnapshotConflict):
        store.upload(str(archive), expected_version=None)

    # Conditional upload on the current version succeeds, on a stale one fails
    archive.write_bytes(b"snapshot-2")
    v2 = store.upload(str(archive), expected_version=v1)
    assert v2 != v1
    with pytest.raises(SnapshotConflict):
        store.upload(str(archive), expected_version=v1)

    # Download returns the latest bytes and their version
    assert store.download(str(out)) == v2 == store.current_version()
    assert out.read_bytes() == b"snapshot-2"


def test_fake_store_contract(fake_store, tmp_path):
    """Verify the in-memory fake honors the StateStore contract."""
    check_store_contract(fake_store, tmp_path)


def test_local_backend_has_no_store():
    """Verify STATE_BACKEND=local means no remote store (case-insensitive)."""
    assert get_state_store("local") is None
    assert get_state_store("LOCAL") is None


def test_unknown_backend_raises():
    """Verify a mistyped backend fails loudly instead of silently running local-only."""
    with pytest.raises(ValueError):
        get_state_store("azure-blob")
