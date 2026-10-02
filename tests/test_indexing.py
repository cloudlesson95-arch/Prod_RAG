from contextlib import contextmanager

from src.core import indexing


def test_reindex_runs_all_steps_inside_state_write(monkeypatch):
    """Verify sync and both retrains happen inside the write block, in order."""
    calls = []

    @contextmanager
    def fake_state_write():
        calls.append("enter")
        yield
        calls.append("exit")

    def fake_sync(force_rebuild=False):
        calls.append("sync")
        return None, {"a.txt"}

    def fake_clustering(changed_sources=None, force_rebuild=False):
        calls.append(("clustering", changed_sources))

    def fake_classifier():
        calls.append("classifier")

    monkeypatch.setattr(indexing, "state_write", fake_state_write)
    monkeypatch.setattr(indexing, "sync_incremental_index", fake_sync)
    monkeypatch.setattr(indexing, "train_clustering", fake_clustering)
    monkeypatch.setattr(indexing, "train_classifier", fake_classifier)

    assert indexing.reindex() == {"a.txt"}
    assert calls == ["enter", "sync", ("clustering", {"a.txt"}), "classifier", "exit"]


def test_sync_and_retrain_never_opens_a_write_block(monkeypatch):
    """Verify the inner step forwards force_rebuild and can run inside a caller's state_write()."""
    calls = []

    def no_state_write():
        raise AssertionError("sync_and_retrain must not enter state_write")

    def fake_sync(force_rebuild=False):
        calls.append(("sync", force_rebuild))
        return None, {"b.txt"}

    def fake_clustering(changed_sources=None, force_rebuild=False):
        calls.append(("clustering", force_rebuild))

    def fake_classifier():
        calls.append("classifier")

    monkeypatch.setattr(indexing, "state_write", no_state_write)
    monkeypatch.setattr(indexing, "sync_incremental_index", fake_sync)
    monkeypatch.setattr(indexing, "train_clustering", fake_clustering)
    monkeypatch.setattr(indexing, "train_classifier", fake_classifier)

    assert indexing.sync_and_retrain(force_rebuild=True) == {"b.txt"}
    assert calls == [("sync", True), ("clustering", True), "classifier"]
