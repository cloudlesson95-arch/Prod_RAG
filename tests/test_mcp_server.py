import pytest
from types import SimpleNamespace
from src.core.mcp_server import search_documents, route_query, get_corpus_stats, build_transport_security

def test_search_documents():
    """Verify search_documents tool returns JSON-serializable list of dicts."""
    results = search_documents(query="cat facts", source_filter="none", k=2)
    assert isinstance(results, list)
    if len(results) > 0:
        assert "content" in results[0]
        assert "source" in results[0]
        assert "metadata" in results[0]

def test_route_query():
    """Verify route_query tool predicts retrieval and source accurately."""
    res = route_query(query="What is a group of cats called?")
    assert "needs_retrieval" in res
    assert "predicted_source" in res
    assert isinstance(res["needs_retrieval"], bool)

def test_get_corpus_stats():
    """Verify get_corpus_stats returns document registry mapping."""
    stats = get_corpus_stats()
    assert isinstance(stats, dict)

def test_transport_security_keeps_sdk_default_when_protection_enabled():
    """Verify the default leaves the SDK's localhost-only Host check in place."""
    assert build_transport_security(True) is None

def test_transport_security_disables_host_check_for_public_deployments():
    """Verify MCP_DNS_REBINDING_PROTECTION=false turns the Host/Origin check off."""
    settings = build_transport_security(False)
    assert settings.enable_dns_rebinding_protection is False

def test_route_query_reports_the_shared_decision(monkeypatch):
    """Verify route_query returns the shared router's decision, probe overrule included (it used to ignore the probe)."""
    from src.core import mcp_server
    from src.routing import router

    vs = SimpleNamespace(_embedding_function=SimpleNamespace(embed_query=lambda text: [1.0, 0.0]))
    monkeypatch.setattr(mcp_server, "get_vectorstore", lambda: vs)
    monkeypatch.setattr(router, "decide_route",
                        lambda emb, vectorstore: router.RouteResult(True, "ingested/batch/quokka.txt", 0.54, 0.75, "probe"))

    assert route_query(query="Where does the quokka live?") == {
        "needs_retrieval": True, "predicted_source": "ingested/batch/quokka.txt",
        "confidence": 0.54, "probe_similarity": 0.75, "reason": "probe",
    }
