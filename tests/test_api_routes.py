from fastapi.testclient import TestClient
from starlette.routing import Mount

from src.core import api


def test_mcp_root_mount_is_last_route():
    """Verify the catch-all MCP mount comes after every API route."""
    last = api.app.routes[-1]
    assert isinstance(last, Mount)
    assert last.path == ""


def test_api_routes_stay_reachable_with_root_mount():
    """Verify /health is served by FastAPI, not swallowed by the MCP mount (no lifespan needed)."""
    client = TestClient(api.app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
