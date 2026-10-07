import os
from datetime import datetime, timedelta, timezone

import pytest

from src.storage import event_store
from src.storage.event_store import AzureBlobEventStore, LocalEventStore, S3EventStore, get_event_store
from src.storage.state_sync import SNAPSHOT_LOCAL_ITEMS

AZURITE_CONNECTION_STRING = os.getenv("AZURITE_CONNECTION_STRING", "")
needs_azurite = pytest.mark.skipif(not AZURITE_CONNECTION_STRING,
                                   reason="set AZURITE_CONNECTION_STRING to run against Azurite")

YESTERDAY = datetime(2026, 10, 6, 23, 59, tzinfo=timezone.utc)
TODAY = datetime(2026, 10, 7, 8, 0, tzinfo=timezone.utc)
LATER = TODAY + timedelta(hours=1)


def check_event_store_contract(store):
    """Behavior every EventStore backend must have"""
    assert store.list_recent("routing", days=7, now=LATER) == []

    store.put("routing", {"source": "a"}, now=YESTERDAY)
    store.put("routing", {"source": "b"}, now=TODAY)
    same_time = [store.put("routing", {"source": "c"}, now=TODAY + timedelta(minutes=1)) for _ in range(2)]
    store.put("eval_run", {"precision_score": 90.0}, now=TODAY)

    # Two writes in the same microsecond are still two records
    assert same_time[0] != same_time[1]

    # Newest first, stamped with their write time, and kinds don't mix
    records = store.list_recent("routing", days=2, now=LATER)
    assert [r["source"] for r in records] == ["c", "c", "b", "a"]
    assert records[-1]["ts"] == YESTERDAY.isoformat()
    assert [r["precision_score"] for r in store.list_recent("eval_run", days=1, now=LATER)] == [90.0]

    # The window counts UTC days back from today, and the limit keeps the newest
    assert [r["source"] for r in store.list_recent("routing", days=1, now=LATER)] == ["c", "c", "b"]
    assert [r["source"] for r in store.list_recent("routing", days=2, limit=3, now=LATER)] == ["c", "c", "b"]

    # Unknown kinds would become arbitrary key prefixes (and local paths)
    with pytest.raises(ValueError):
        store.put("../outside", {})


def test_local_store_contract(tmp_path):
    """Verify the local backend honors the EventStore contract."""
    check_event_store_contract(LocalEventStore(str(tmp_path)))


def test_local_store_writes_outside_the_snapshot(tmp_path):
    """Verify local events land in LOCAL_DIR/events, which pack_state never includes, with no temp file left."""
    LocalEventStore(str(tmp_path)).put("routing", {"source": "a"}, now=TODAY)

    files = list((tmp_path / "events" / "routing" / "2026-10-07").iterdir())
    assert len(files) == 1 and files[0].suffix == ".json"
    assert "events" not in SNAPSHOT_LOCAL_ITEMS


def test_s3_store_contract(moto_bucket):
    """Verify the S3 backend honors the same contract as the local one."""
    check_event_store_contract(S3EventStore(moto_bucket, "us-east-1"))


@needs_azurite
def test_azure_blob_store_contract(azurite_container):
    """Verify the Azure backend honors the same contract as the local one."""
    check_event_store_contract(AzureBlobEventStore(azurite_container, connection_string=AZURITE_CONNECTION_STRING))


def test_local_backend_uses_local_files():
    """Verify STATE_BACKEND=local still gets an event store (local files), unlike the state store."""
    assert isinstance(get_event_store("LOCAL"), LocalEventStore)


def test_unknown_backend_raises():
    """Verify a mistyped backend fails loudly."""
    with pytest.raises(ValueError):
        get_event_store("azure-blob")


def test_cloud_backends_require_their_config(monkeypatch):
    """Verify a missing bucket or account URL fails at startup instead of at the first write."""
    monkeypatch.setattr(event_store, "S3_STATE_BUCKET", "")
    monkeypatch.setattr(event_store, "AZURE_STORAGE_ACCOUNT_URL", "")
    monkeypatch.setattr(event_store, "AZURE_STORAGE_CONNECTION_STRING", "")
    with pytest.raises(ValueError):
        get_event_store("s3")
    with pytest.raises(ValueError):
        get_event_store("azure_blob")
