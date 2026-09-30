import abc
from src.config import STATE_BACKEND
from src.logging_config import setup_logging

logger = setup_logging(__name__)


class SnapshotConflict(Exception):
    """The stored snapshot is not the version the caller expected."""


class StateStore(abc.ABC):
    """Remote storage for the single state snapshot archive.

    Versions are opaque strings (ETags). Implementations must raise on any error
    other than "snapshot does not exist" -- never return None for auth or network
    failures, or the caller will mistake an outage for an empty store.
    """

    @abc.abstractmethod
    def download(self, dest_path: str) -> str | None:
        """Download the snapshot to dest_path.

        Returns:
            str | None: Version of the downloaded bytes, or None if no snapshot exists.
        """
        pass

    @abc.abstractmethod
    def current_version(self) -> str | None:
        """Return the stored snapshot's version without downloading it, or None if none exists."""
        pass

    @abc.abstractmethod
    def upload(self, src_path: str, expected_version: str | None) -> str:
        """Upload src_path as the new snapshot, only if the stored version still matches.

        Args:
            src_path: Local archive to upload.
            expected_version: Version the caller's state is based on.
                None means the snapshot must not exist yet (create-only).

        Returns:
            str: Version of the newly stored snapshot.

        Raises:
            SnapshotConflict: If the stored version differs from expected_version.
        """
        pass


def get_state_store(backend: str = STATE_BACKEND) -> StateStore | None:
    """Return the configured StateStore, or None when state is local-only."""
    backend = backend.lower()
    if backend == "local":
        return None
    raise ValueError(f"Unknown STATE_BACKEND '{backend}' (expected 'local', 'azure_blob' or 's3')")
