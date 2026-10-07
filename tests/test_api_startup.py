from types import SimpleNamespace

import pytest

from src.core import api
from src.ingestion.demo import DemoStore


@pytest.fixture
def startup_calls(monkeypatch):
    """Run startup_event with fakes and return the call order. Module globals are restored afterwards."""
    calls = []

    def fake_vectorstore():
        calls.append("vectorstore")
        return SimpleNamespace(embeddings="loaded-embeddings")

    # startup_event rebinds these globals; registering them with monkeypatch restores the originals after the test
    for name in ("router", "vectorstore", "answer_llm", "demo_store", "event_store"):
        monkeypatch.setattr(api, name, None)
    monkeypatch.setattr(api, "initialize_state", lambda: calls.append("state"))
    monkeypatch.setattr(api, "get_event_store", lambda: calls.append("events"))
    monkeypatch.setattr(api, "setup_router", lambda: calls.append("router"))
    monkeypatch.setattr(api, "create_or_get_vectorstore", fake_vectorstore)
    monkeypatch.setattr(api, "create_llm", lambda model: calls.append("llm"))

    api.startup_event()
    return calls


def test_startup_initializes_state_before_opening_chroma(startup_calls):
    """Verify state is restored/seeded before the vector store is opened."""
    assert startup_calls[0] == "state"
    assert "vectorstore" in startup_calls


def test_startup_creates_demo_store_with_loaded_embeddings(startup_calls):
    """Verify the demo store is published as a module global and reuses the startup embedding model."""
    assert isinstance(api.demo_store, DemoStore)
    assert api.demo_store._embeddings == "loaded-embeddings"
