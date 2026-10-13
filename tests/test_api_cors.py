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


def test_a_rate_limit_response_reaches_the_frontend_with_retry_after(monkeypatch, rate_limit_error):
    """Verify the 503 for a rate limit names the frontend's origin and lets its JavaScript read the Retry-After value."""
    def rate_limited(*args, **kwargs):
        raise rate_limit_error

    monkeypatch.setattr(api, "answer_question", rate_limited)
    response = TestClient(api.app).post("/query", json={"question": "Hi?"}, headers={"Origin": ALLOWED})

    assert response.status_code == 503
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert response.headers["Retry-After"] == "7"
    assert "retry-after" in response.headers["access-control-expose-headers"].lower()
