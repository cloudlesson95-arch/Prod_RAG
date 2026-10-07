"""Append-only event records next to the state snapshot, never inside it.

Routing decisions (one per /query) and eval runs (one per live-eval) can't go into the snapshot: only state_write()
publishes it, one writer at a time. Here every record is its own small object under events/<kind>/<UTC day>/ with a
unique key, so writers never conflict with each other or with snapshot writes. It lives in the state container or
bucket, which the app and the GitHub identities can already read and write.
"""
import abc
import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import boto3
from botocore.config import Config
from azure.storage.blob import ContentSettings, LinearRetry

from src.config import (
    STATE_BACKEND, LOCAL_DIR,
    AZURE_STORAGE_ACCOUNT_URL, AZURE_STATE_CONTAINER, AZURE_STORAGE_CONNECTION_STRING,
    S3_STATE_BUCKET, AWS_REGION,
)
from src.storage.state_store import blob_service_client

EVENT_KINDS = ("routing", "eval_run")  # one record per /query request; one per live-eval run
EVENTS_PREFIX = "events/"
READ_WORKERS = 8  # parallel list and read calls; boto3's default pool holds 10 connections

# Short timeouts and one quick retry: routing events are written on the /query path, where a slow store must not
# hold up the answer (the caller treats a failed write as a warning). Azure Storage's default retry policy waits
# about 15 s before its first retry, so it gets a linear backoff of about 1 s instead.
S3_CLIENT_CONFIG = Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 2, "mode": "standard"})
AZURE_CLIENT_OPTIONS = {"connection_timeout": 3, "read_timeout": 5,
                        "retry_policy": LinearRetry(backoff=1, random_jitter_range=1, retry_total=1)}


class EventStore(abc.ABC):
    """Append-only JSON records, grouped by kind and UTC day."""

    def put(self, kind: str, record: dict, now: datetime | None = None) -> str:
        """Store one record, stamped with "ts" (the UTC write time), under a new unique key; return the key."""
        _check_kind(kind)
        now = now or datetime.now(timezone.utc)
        key = f"{EVENTS_PREFIX}{kind}/{now:%Y-%m-%d}/{now:%H%M%S.%f}Z-{secrets.token_hex(4)}.json"
        self._write(key, json.dumps({"ts": now.isoformat(), **record}, ensure_ascii=False).encode("utf-8"))
        return key

    def list_recent(self, kind: str, days: int, limit: int = 1000, now: datetime | None = None) -> list[dict]:
        """Records of one kind from the last `days` UTC days (today included), newest first, at most `limit`."""
        _check_kind(kind)
        today = (now or datetime.now(timezone.utc)).date()
        prefixes = [f"{EVENTS_PREFIX}{kind}/{today - timedelta(days=n):%Y-%m-%d}/" for n in range(days)]
        with ThreadPoolExecutor(max_workers=READ_WORKERS) as pool:
            keys = [key for day in pool.map(self._list, prefixes) for key in sorted(day, reverse=True)]
            return [json.loads(data) for data in pool.map(self._read, keys[:limit])]

    @abc.abstractmethod
    def _write(self, key: str, data: bytes) -> None:
        pass

    @abc.abstractmethod
    def _list(self, prefix: str) -> list[str]:
        """Keys directly under prefix (one day's folder)."""
        pass

    @abc.abstractmethod
    def _read(self, key: str) -> bytes:
        pass


def _check_kind(kind: str) -> None:
    """Kinds become key prefixes and, locally, folder names, so only known ones are accepted."""
    if kind not in EVENT_KINDS:
        raise ValueError(f"Unknown event kind '{kind}' (expected one of: {', '.join(EVENT_KINDS)})")


class LocalEventStore(EventStore):
    """Files under root/events/ (LOCAL_DIR locally). Not in SNAPSHOT_LOCAL_ITEMS, so never packed into a snapshot."""

    def __init__(self, root: str):
        self._root = root

    def _path(self, key: str) -> str:
        return os.path.join(self._root, *key.rstrip("/").split("/"))

    def _write(self, key, data):
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "wb") as f:
            f.write(data)
        os.replace(path + ".tmp", path)  # a reader never sees a half-written record

    def _list(self, prefix):
        folder = self._path(prefix)
        if not os.path.isdir(folder):
            return []
        return [prefix + name for name in os.listdir(folder) if name.endswith(".json")]

    def _read(self, key):
        with open(self._path(key), "rb") as f:
            return f.read()


class S3EventStore(EventStore):
    """Objects in the state bucket (the StateSnapshotAccess policies cover bucket/* and listing)."""

    def __init__(self, bucket: str, region: str):
        if not bucket:
            raise ValueError("STATE_BACKEND=s3 needs S3_STATE_BUCKET.")
        self._s3 = boto3.client("s3", region_name=region, config=S3_CLIENT_CONFIG)
        self._bucket = bucket

    def _write(self, key, data):
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType="application/json")

    def _list(self, prefix):
        pages = self._s3.get_paginator("list_objects_v2").paginate(Bucket=self._bucket, Prefix=prefix)
        return [item["Key"] for page in pages for item in page.get("Contents", [])]

    def _read(self, key):
        return self._s3.get_object(Bucket=self._bucket, Key=key)["Body"].read()


class AzureBlobEventStore(EventStore):
    """Blobs in the state container ("Storage Blob Data Contributor" on it covers listing, reading and writing)."""

    def __init__(self, container: str, account_url: str = "", connection_string: str = ""):
        service = blob_service_client(account_url, connection_string, **AZURE_CLIENT_OPTIONS)
        self._container = service.get_container_client(container)

    def _write(self, key, data):
        self._container.upload_blob(key, data, content_settings=ContentSettings(content_type="application/json"))

    def _list(self, prefix):
        return list(self._container.list_blob_names(name_starts_with=prefix))

    def _read(self, key):
        return self._container.download_blob(key).readall()


def get_event_store(backend: str = STATE_BACKEND) -> EventStore:
    """Return the event store next to the configured state store: local files when STATE_BACKEND=local."""
    backend = backend.lower()
    if backend == "local":
        return LocalEventStore(LOCAL_DIR)
    if backend == "azure_blob":
        return AzureBlobEventStore(AZURE_STATE_CONTAINER, AZURE_STORAGE_ACCOUNT_URL, AZURE_STORAGE_CONNECTION_STRING)
    if backend == "s3":
        return S3EventStore(S3_STATE_BUCKET, AWS_REGION)

    raise ValueError(f"Unknown STATE_BACKEND '{backend}' (expected 'local', 'azure_blob' or 's3')")
