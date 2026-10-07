from fastapi.testclient import TestClient

from src.core import api

ALLOWED = "http://localhost:3000"  # the CORS_ALLOW_ORIGINS default; run the tests without that variable set
PREFLIGHT = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}


def test_preflight_from_the_frontend_origin_is_allowed():
    """Verify the browser's preflight for a JSON POST /query from the frontend's origin succeeds."""
    response = TestClient(api.app).options("/query", headers={"Origin": ALLOWED, **PREFLIGHT})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert "POST" in response.headers["access-control-allow-methods"]


def test_preflight_from_another_origin_is_refused():
    """Verify an origin that isn't configured gets no CORS permission."""
    response = TestClient(api.app).options("/query", headers={"Origin": "https://evil.example", **PREFLIGHT})

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_error_responses_carry_cors_headers_and_expose_retry_after():
    """Verify an error response still names the frontend's origin, so its JavaScript can read the status, detail and Retry-After."""
    response = TestClient(api.app).post("/query", json={"question": "  "}, headers={"Origin": ALLOWED})

    assert response.status_code == 400
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert "retry-after" in response.headers["access-control-expose-headers"].lower()
