import hashlib
from contextlib import contextmanager

import pytest

from src.ingestion import batch
from src.storage.state_sync import StateReadOnlyError


@pytest.fixture
def batch_env(tmp_path, monkeypatch):
    """Point the batch at tmp dirs and fake the state machinery. Returns (inbox, batch_dir, calls)."""
    inbox, batch_dir = tmp_path / "inbox", tmp_path / "data" / "ingested" / "batch"
    inbox.mkdir()
    calls = []

    @contextmanager
    def fake_state_write():
        calls.append("enter")
        yield
        calls.append("exit")

    def fake_sync_and_retrain():
        calls.append(("sync", sorted(p.name for p in batch_dir.iterdir())))
        return {"ingested/batch/changed.txt"}

    monkeypatch.setattr(batch, "BATCH_DIR", str(batch_dir))
    monkeypatch.setattr(batch, "initialize_state", lambda: calls.append("init"))
    monkeypatch.setattr(batch, "read_only_reason", lambda: None)
    monkeypatch.setattr(batch, "read_local_version", lambda: "v2")
    monkeypatch.setattr(batch, "state_write", fake_state_write)
    monkeypatch.setattr(batch, "sync_and_retrain", fake_sync_and_retrain)
    # Questions: no LLM, nothing missing, and generation yields nothing unless a test says otherwise
    monkeypatch.setattr(batch, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(batch, "sources_missing_questions", lambda: [])
    monkeypatch.setattr(batch, "create_llm", lambda provider: "fake-llm")
    monkeypatch.setattr(batch, "generate_questions", lambda text, llm: [])
    monkeypatch.setattr(batch, "replace_questions",
                        lambda source, file_hash, items: calls.append(("questions", source, file_hash, len(items))))
    monkeypatch.setattr(batch, "create_or_get_vectorstore", lambda: "fake-vectorstore")
    monkeypatch.setattr(batch, "benchmark_routing_failures", lambda vectorstore: [])
    return inbox, batch_dir, calls


def test_new_files_are_written_and_indexed_in_one_write_block(batch_env):
    """Verify the batch starts from the latest snapshot, then writes and indexes everything in one publish."""
    inbox, batch_dir, calls = batch_env
    (inbox / "Quokkas.txt").write_bytes(b"Quokkas live on Rottnest Island.")
    (inbox / "notes.md").write_bytes(b"# Notes\nCats purr.")

    result = batch.ingest_batch(str(inbox))

    assert calls == ["init", "enter", ("sync", ["notes.md", "quokkas.txt"]), "exit"]
    assert sorted(result.added) == ["notes.md", "quokkas.txt"]
    assert (result.published, result.state_version) == (True, "v2")
    assert (batch_dir / "quokkas.txt").read_bytes() == b"Quokkas live on Rottnest Island."


def test_unchanged_batch_publishes_nothing(batch_env):
    """Verify re-running the same inbox never enters state_write, so no snapshot is uploaded."""
    inbox, batch_dir, calls = batch_env
    batch_dir.mkdir(parents=True)
    (batch_dir / "a.txt").write_bytes(b"same text")
    (inbox / "a.txt").write_bytes(b"same text")

    result = batch.ingest_batch(str(inbox))

    assert calls == ["init"]
    assert result.unchanged == ["a.txt"]
    assert not result.published


def test_changed_file_is_reported_as_modified(batch_env):
    """Verify a new version of a stored file replaces it and is re-indexed."""
    inbox, batch_dir, calls = batch_env
    batch_dir.mkdir(parents=True)
    (batch_dir / "a.txt").write_bytes(b"old text")
    (inbox / "a.txt").write_bytes(b"new text")

    result = batch.ingest_batch(str(inbox))

    assert result.modified == ["a.txt"]
    assert (batch_dir / "a.txt").read_bytes() == b"new text"
    assert calls[-1] == "exit"


def test_bad_files_are_reported_and_never_written(batch_env):
    """Verify unsupported, empty and name-colliding files are reported while good files still go in."""
    inbox, batch_dir, calls = batch_env
    (inbox / "good.txt").write_bytes(b"Cats purr.")
    (inbox / "tool.exe").write_bytes(b"MZ")
    (inbox / "empty.txt").write_bytes(b"   ")
    (inbox / "my report.txt").write_bytes(b"first")
    (inbox / "my-report.txt").write_bytes(b"second")
    (inbox / "subfolder").mkdir()

    result = batch.ingest_batch(str(inbox))

    assert sorted(name for name, _ in result.failed) == ["empty.txt", "my-report.txt", "tool.exe"]
    assert sorted(p.name for p in batch_dir.iterdir()) == ["good.txt", "my-report.txt"]
    assert (batch_dir / "my-report.txt").read_bytes() == b"first"


def test_read_only_state_stops_before_any_write(batch_env, monkeypatch):
    """Verify an unreachable state store stops the batch before anything is written."""
    inbox, batch_dir, calls = batch_env
    (inbox / "a.txt").write_bytes(b"text")
    monkeypatch.setattr(batch, "read_only_reason", lambda: "state store unavailable at startup")

    with pytest.raises(StateReadOnlyError):
        batch.ingest_batch(str(inbox))
    assert calls == ["init"]
    assert not batch_dir.exists()


def test_missing_inbox_fails_before_touching_state(batch_env, tmp_path):
    """Verify a typo in --dir doesn't trigger a snapshot restore."""
    _, _, calls = batch_env
    with pytest.raises(FileNotFoundError):
        batch.ingest_batch(str(tmp_path / "no-such-inbox"))
    assert calls == []


def _qa(n):
    return [{"question": f"Question {i}?", "answer": "An answer.", "context": "A chunk."} for i in range(n)]


def test_new_files_get_questions_stored_before_the_retrain(batch_env, monkeypatch):
    """Verify questions for new files are stored inside the write block, before the retrain, under the written file's hash."""
    inbox, batch_dir, calls = batch_env
    (inbox / "quokkas.txt").write_bytes(b"Quokkas live on Rottnest Island.")
    monkeypatch.setattr(batch, "generate_questions", lambda text, llm: _qa(2))

    result = batch.ingest_batch(str(inbox))

    file_hash = hashlib.sha256((batch_dir / "quokkas.txt").read_bytes()).hexdigest()
    assert calls == ["init", "enter", ("questions", "ingested/batch/quokkas.txt", file_hash, 2),
                     ("sync", ["quokkas.txt"]), "exit"]
    assert (result.questions_generated, result.question_sources) == (2, ["ingested/batch/quokkas.txt"])


def test_documents_without_questions_are_filled_in_even_with_nothing_new(batch_env, monkeypatch, tmp_path):
    """Verify an indexed document without questions (here a seed file) gets them, and that alone publishes a snapshot."""
    inbox, batch_dir, calls = batch_env
    batch_dir.mkdir(parents=True)
    (batch_dir / "a.txt").write_bytes(b"same text")
    (inbox / "a.txt").write_bytes(b"same text")
    (tmp_path / "data" / "cat-facts.txt").write_bytes(b"A group of cats is called a clowder.")
    monkeypatch.setattr(batch, "sources_missing_questions", lambda: ["cat-facts.txt"])
    monkeypatch.setattr(batch, "generate_questions", lambda text, llm: _qa(1))

    result = batch.ingest_batch(str(inbox))

    seed_hash = hashlib.sha256(b"A group of cats is called a clowder.").hexdigest()
    assert calls == ["init", "enter", ("questions", "cat-facts.txt", seed_hash, 1), ("sync", ["a.txt"]), "exit"]
    assert result.unchanged == ["a.txt"] and result.published


def test_skip_questions_makes_no_llm_calls(batch_env, monkeypatch):
    """Verify --skip-questions ingests the files without creating an LLM or asking it anything."""
    inbox, batch_dir, calls = batch_env
    (inbox / "a.txt").write_bytes(b"text")
    monkeypatch.setattr(batch, "create_llm", lambda provider: pytest.fail("LLM created"))
    monkeypatch.setattr(batch, "generate_questions", lambda text, llm: pytest.fail("questions generated"))

    result = batch.ingest_batch(str(inbox), generate=False)

    assert calls == ["init", "enter", ("sync", ["a.txt"]), "exit"]
    assert result.published and result.questions_generated == 0


def test_no_llm_still_ingests_the_files(batch_env, monkeypatch):
    """Verify a missing key or unreachable provider costs the questions, not the batch."""
    inbox, batch_dir, calls = batch_env
    (inbox / "a.txt").write_bytes(b"text")

    def no_llm(provider):
        raise RuntimeError("GROQ_API_KEY is not set")

    monkeypatch.setattr(batch, "create_llm", no_llm)

    result = batch.ingest_batch(str(inbox))

    assert calls == ["init", "enter", ("sync", ["a.txt"]), "exit"]
    assert result.published and result.questions_generated == 0


def test_misrouted_benchmark_stops_the_publish(batch_env, monkeypatch):
    """Verify a retrain that misroutes a benchmark question raises inside the write block, so nothing is uploaded."""
    inbox, batch_dir, calls = batch_env
    (inbox / "clowder.md").write_bytes(b"A group of cats is called a clowder.")
    failure = "'What is a group of cats called?': expected cat-facts.txt, routed to ingested/batch/clowder.md (classifier)"
    monkeypatch.setattr(batch, "benchmark_routing_failures", lambda vectorstore: [failure])

    with pytest.raises(batch.RoutingRegression) as raised:
        batch.ingest_batch(str(inbox))

    assert raised.value.failures == [failure]
    assert calls == ["init", "enter", ("sync", ["clowder.md"])]  # no "exit": the block never finished, so no upload
