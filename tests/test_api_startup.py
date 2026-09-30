from src.core import api


def test_startup_initializes_state_before_opening_chroma(monkeypatch):
    """Verify state is restored/seeded before the vector store is opened."""
    calls = []
    monkeypatch.setattr(api, "initialize_state", lambda: calls.append("state"))
    monkeypatch.setattr(api, "setup_router", lambda: calls.append("router"))
    monkeypatch.setattr(api, "create_or_get_vectorstore", lambda: calls.append("vectorstore"))
    monkeypatch.setattr(api, "create_llm", lambda model: calls.append("llm"))

    api.startup_event()

    assert calls[0] == "state"
    assert "vectorstore" in calls
