import abc
import boto3
from botocore.exceptions import ClientError

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, StorageErrorCode

from src.config import (
    STATE_BACKEND, STATE_SNAPSHOT_NAME,
    AZURE_STORAGE_ACCOUNT_URL, AZURE_STATE_CONTAINER, AZURE_STORAGE_CONNECTION_STRING,
    S3_STATE_BUCKET, AWS_REGION,
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


def blob_service_client(account_url: str = "", connection_string: str = "", **client_options) -> BlobServiceClient:
    """Client for the state storage account, shared by the snapshot and event stores.

    Raises ValueError when neither an account URL nor a connection string (Azurite only) is configured.
    """
    if connection_string:
        return BlobServiceClient.from_connection_string(connection_string, **client_options)
    if account_url:
        return BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential(), **client_options)
    raise ValueError("STATE_BACKEND=azure_blob needs AZURE_STORAGE_ACCOUNT_URL "
                     "(or AZURE_STORAGE_CONNECTION_STRING for Azurite).")


class AzureBlobStateStore(StateStore):
    """Snapshot stored as one Azure blob; versions are the blob's ETag.

    Authenticates with DefaultAzureCredential (the Container App's managed identity,
    or your `az login` locally) unless a connection string is given (Azurite only).
    """

    def __init__(self, container: str, blob_name: str, account_url: str = "", connection_string: str = ""):
        service = blob_service_client(account_url, connection_string)
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


class S3StateStore(StateStore):
    """Snapshot stored as one S3 object; versions are the object's ETag.

    Authenticates with the default AWS credential chain (the Lambda execution role,
    or your AWS profile locally).
    """

    def __init__(self, bucket: str, key: str, region: str):
        if not bucket:
            raise ValueError("STATE_BACKEND=s3 needs S3_STATE_BUCKET.")
        self._s3 = boto3.client("s3", region_name=region)
        self._bucket = bucket
        self._key = key

    def download(self, dest_path: str) -> str | None:
        try:
            response = self._s3.get_object(Bucket=self._bucket, Key=self._key)
        except ClientError as e:
            if self._is_missing_object(e):
                return None
            raise
        with open(dest_path, "wb") as f:
            for chunk in response["Body"].iter_chunks(chunk_size=1024 * 1024):
                f.write(chunk)
        return response["ETag"]

    def current_version(self) -> str | None:
        try:
            return self._s3.head_object(Bucket=self._bucket, Key=self._key)["ETag"]
        except ClientError as e:
            if self._is_missing_object(e):
                return None
            raise

    def upload(self, src_path: str, expected_version: str | None) -> str:
        condition = {"IfNoneMatch": "*"} if expected_version is None else {"IfMatch": expected_version}
        with open(src_path, "rb") as data:
            try:
                response = self._s3.put_object(Bucket=self._bucket, Key=self._key, Body=data, **condition)
            except ClientError as e:
                # 412: the condition failed; 409: another conditional write to this key was in flight
                if e.response.get("Error", {}).get("Code") in ("PreconditionFailed", "ConditionalRequestConflict"):
                    raise SnapshotConflict(f"Snapshot changed since version {expected_version!r}") from e
                raise
        return response["ETag"]

    def _is_missing_object(self, e: ClientError) -> bool:
        """True only if the bucket exists and the snapshot object doesn't."""
        code = e.response.get("Error", {}).get("Code")
        if code == "NoSuchKey":
            return True
        if code in ("404", "NotFound"):
            # HEAD responses have no body, so a missing bucket also looks like a plain 404.
            self._s3.head_bucket(Bucket=self._bucket)  # raises if the bucket doesn't exist
            return True
        return False


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
    if backend == "s3":
        return S3StateStore(bucket=S3_STATE_BUCKET, key=STATE_SNAPSHOT_NAME, region=AWS_REGION)

    raise ValueError(f"Unknown STATE_BACKEND '{backend}' (expected 'local', 'azure_blob' or 's3')")
