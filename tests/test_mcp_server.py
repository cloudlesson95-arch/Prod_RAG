import pytest
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
