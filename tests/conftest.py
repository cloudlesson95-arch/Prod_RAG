import pytest
from src.storage.state_store import StateStore, SnapshotConflict


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
