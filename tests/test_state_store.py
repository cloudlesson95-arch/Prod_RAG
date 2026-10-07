import os
from botocore.exceptions import ClientError

import pytest
from azure.core.exceptions import ResourceNotFoundError

from src.storage import state_store
from src.storage.state_store import get_state_store, SnapshotConflict, AzureBlobStateStore, S3StateStore


AZURITE_CONNECTION_STRING = os.getenv("AZURITE_CONNECTION_STRING", "")
needs_azurite = pytest.mark.skipif(not AZURITE_CONNECTION_STRING,
                                   reason="set AZURITE_CONNECTION_STRING to run against Azurite")


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


def test_azure_backend_requires_url_or_connection_string(monkeypatch):
    """Verify a missing Azure config fails at startup instead of at the first write."""
    monkeypatch.setattr(state_store, "AZURE_STORAGE_ACCOUNT_URL", "")
    monkeypatch.setattr(state_store, "AZURE_STORAGE_CONNECTION_STRING", "")
    with pytest.raises(ValueError):
        get_state_store("azure_blob")


@needs_azurite
def test_azure_blob_store_contract(azurite_container, tmp_path):
    """Verify the Azure backend honors the same contract as the fake."""
    store = AzureBlobStateStore(azurite_container, "state.tar.gz", connection_string=AZURITE_CONNECTION_STRING)
    check_store_contract(store, tmp_path)


@needs_azurite
def test_azure_blob_missing_container_is_an_error_not_an_empty_store(tmp_path):
    """Verify a wrong container name raises instead of looking like 'no snapshot yet'."""
    store = AzureBlobStateStore("no-such-container", "state.tar.gz", connection_string=AZURITE_CONNECTION_STRING)
    with pytest.raises(ResourceNotFoundError):
        store.download(str(tmp_path / "out"))
    with pytest.raises(ResourceNotFoundError):
        store.current_version()


def test_s3_backend_requires_bucket(monkeypatch):
    """Verify a missing bucket name fails at startup instead of at the first write."""
    monkeypatch.setattr(state_store, "S3_STATE_BUCKET", "")
    with pytest.raises(ValueError):
        get_state_store("s3")


def test_s3_store_contract(moto_bucket, tmp_path):
    """Verify the S3 backend honors the same contract as the fake and Azure."""
    store = S3StateStore(bucket=moto_bucket, key="state.tar.gz", region="us-east-1")
    check_store_contract(store, tmp_path)


def test_s3_missing_bucket_is_an_error_not_an_empty_store(moto_bucket, tmp_path):
    """Verify a wrong bucket name raises instead of looking like 'no snapshot yet'."""
    store = S3StateStore(bucket="no-such-bucket", key="state.tar.gz", region="us-east-1")
    with pytest.raises(ClientError):
        store.download(str(tmp_path / "out"))
    with pytest.raises(ClientError):
        store.current_version()
