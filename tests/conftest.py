import os
import uuid

import boto3
import pytest
from azure.storage.blob import BlobServiceClient

from src.storage.state_store import StateStore, SnapshotConflict

AZURITE_CONNECTION_STRING = os.getenv("AZURITE_CONNECTION_STRING", "")


class FakeStateStore(StateStore):
    """In-memory StateStore with the same conditional-write semantics as Blob/S3."""

    def __init__(self):
        self.data: bytes | None = None
        self.version: str | None = None
        self.uploads = 0

    def download(self, dest_path):
        if self.data is None:
            return None
        with open(dest_path, "wb") as f:
            f.write(self.data)
        return self.version

    def current_version(self):
        return self.version

    def upload(self, src_path, expected_version):
        if expected_version != self.version:
            raise SnapshotConflict(f"expected {expected_version!r}, stored {self.version!r}")
        with open(src_path, "rb") as f:
            self.data = f.read()
        self.uploads += 1
        self.version = f"v{self.uploads}"
        return self.version


@pytest.fixture
def fake_store():
    return FakeStateStore()


@pytest.fixture
def azurite_container():
    """Create a throwaway container in Azurite and delete it after the test."""
    service = BlobServiceClient.from_connection_string(AZURITE_CONNECTION_STRING)
    name = f"test-{uuid.uuid4().hex[:12]}"
    service.create_container(name)
    yield name
    service.delete_container(name)


@pytest.fixture
def moto_bucket(monkeypatch):
    """A bucket in moto's in-memory S3, with fake credentials so real AWS is never touched."""
    moto = pytest.importorskip("moto")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="test-state")
        yield "test-state"
