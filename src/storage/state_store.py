import abc

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, StorageErrorCode

from src.config import (
    STATE_BACKEND, STATE_SNAPSHOT_NAME,
    AZURE_STORAGE_ACCOUNT_URL, AZURE_STATE_CONTAINER, AZURE_STORAGE_CONNECTION_STRING,
)
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


class AzureBlobStateStore(StateStore):
    """Snapshot stored as one Azure blob; versions are the blob's ETag.

    Authenticates with DefaultAzureCredential (the Container App's managed identity,
    or your `az login` locally) unless a connection string is given (Azurite only).
    """

    def __init__(self, container: str, blob_name: str, account_url: str = "", connection_string: str = ""):
        if connection_string:
            service = BlobServiceClient.from_connection_string(connection_string)
        elif account_url:
            service = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
        else:
            raise ValueError("STATE_BACKEND=azure_blob needs AZURE_STORAGE_ACCOUNT_URL "
                             "(or AZURE_STORAGE_CONNECTION_STRING for Azurite).")
        self._blob = service.get_blob_client(container=container, blob=blob_name)

    def download(self, dest_path: str) -> str | None:
        try:
            downloader = self._blob.download_blob()
        except ResourceNotFoundError as e:
            if e.error_code != StorageErrorCode.BLOB_NOT_FOUND:
                raise  # e.g. ContainerNotFound: a misconfiguration, not an empty store
            return None
        with open(dest_path, "wb") as f:
            downloader.readinto(f)
        return downloader.properties.etag

    def current_version(self) -> str | None:
        try:
            return self._blob.get_blob_properties().etag
        except ResourceNotFoundError as e:
            if e.error_code != StorageErrorCode.BLOB_NOT_FOUND:
                raise
            return None

    def upload(self, src_path: str, expected_version: str | None) -> str:
        with open(src_path, "rb") as data:
            try:
                if expected_version is None:
                    result = self._blob.upload_blob(data, overwrite=False)
                else:
                    result = self._blob.upload_blob(
                        data, overwrite=True,
                        etag=expected_version, match_condition=MatchConditions.IfNotModified,
                    )
            except (ResourceExistsError, ResourceModifiedError) as e:
                raise SnapshotConflict(f"Snapshot changed since version {expected_version!r}") from e
        return result["etag"]


def get_state_store(backend: str = STATE_BACKEND) -> StateStore | None:
    """Return the configured StateStore, or None when state is local-only."""
    backend = backend.lower()
    if backend == "local":
        return None
    if backend == "azure_blob":
        return AzureBlobStateStore(
            container=AZURE_STATE_CONTAINER,
            blob_name=STATE_SNAPSHOT_NAME,
            account_url=AZURE_STORAGE_ACCOUNT_URL,
            connection_string=AZURE_STORAGE_CONNECTION_STRING,
        )
    raise ValueError(f"Unknown STATE_BACKEND '{backend}' (expected 'local', 'azure_blob' or 's3')")
