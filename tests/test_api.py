"""Integration tests for the HTTP API endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage import InMemoryStorage


@pytest.fixture(autouse=True)
def inject_memory_storage():
    """Replace the default SQLAlchemy storage with in-memory for each test."""
    storage = InMemoryStorage()
    app.state.storage = storage
    yield storage
    # Cleanup
    del app.state.storage


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# POST /api/shorten
# ---------------------------------------------------------------------------

class TestShorten:
    def test_happy_path(self, client):
        resp = client.post("/api/shorten", json={"url": "https://example.com"})
        assert resp.status_code == 201
        data = resp.json()
        assert "code" in data
        assert "short_url" in data
        assert len(data["code"]) == 6
        assert data["code"] in data["short_url"]

    def test_invalid_scheme_rejected(self, client):
        resp = client.post("/api/shorten", json={"url": "ftp://example.com"})
        assert resp.status_code == 422

    def test_plain_string_rejected(self, client):
        resp = client.post("/api/shorten", json={"url": "not-a-url"})
        assert resp.status_code == 422

    def test_missing_url_field_rejected(self, client):
        resp = client.post("/api/shorten", json={})
        assert resp.status_code == 422

    def test_http_url_accepted(self, client):
        resp = client.post("/api/shorten", json={"url": "http://example.com/path"})
        assert resp.status_code == 201

    def test_two_shortenings_produce_different_codes(self, client):
        r1 = client.post("/api/shorten", json={"url": "https://example.com"})
        r2 = client.post("/api/shorten", json={"url": "https://other.com"})
        assert r1.json()["code"] != r2.json()["code"]


# ---------------------------------------------------------------------------
# GET /{code}  (redirect)
# ---------------------------------------------------------------------------

class TestRedirect:
    def test_redirect_to_original_url(self, client):
        shorten_resp = client.post("/api/shorten", json={"url": "https://example.com/page"})
        code = shorten_resp.json()["code"]
        resp = client.get(f"/{code}", follow_redirects=False)
        assert resp.status_code == 307
        assert resp.headers["location"] == "https://example.com/page"

    def test_redirect_increments_hits(self, client, inject_memory_storage):
        shorten_resp = client.post("/api/shorten", json={"url": "https://example.com"})
        code = shorten_resp.json()["code"]
        # Two hits
        client.get(f"/{code}", follow_redirects=False)
        client.get(f"/{code}", follow_redirects=False)
        record = inject_memory_storage.get(code)
        assert record.hits == 2

    def test_unknown_code_returns_404(self, client):
        resp = client.get("/zzzzzz", follow_redirects=False)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/stats/{code}
# ---------------------------------------------------------------------------

class TestStats:
    def test_stats_for_known_code(self, client):
        shorten_resp = client.post("/api/shorten", json={"url": "https://example.com"})
        code = shorten_resp.json()["code"]
        resp = client.get(f"/api/stats/{code}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == code
        assert data["url"] == "https://example.com"
        assert data["hits"] == 0
        assert "created_at" in data

    def test_stats_reflect_hits(self, client):
        shorten_resp = client.post("/api/shorten", json={"url": "https://example.com"})
        code = shorten_resp.json()["code"]
        client.get(f"/{code}", follow_redirects=False)
        client.get(f"/{code}", follow_redirects=False)
        stats = client.get(f"/api/stats/{code}").json()
        assert stats["hits"] == 2

    def test_stats_unknown_code_returns_404(self, client):
        resp = client.get("/api/stats/zzzzzz")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/{code}
# ---------------------------------------------------------------------------

class TestDelete:
    def test_delete_existing_returns_204(self, client):
        shorten_resp = client.post("/api/shorten", json={"url": "https://example.com"})
        code = shorten_resp.json()["code"]
        resp = client.delete(f"/api/{code}")
        assert resp.status_code == 204

    def test_deleted_code_not_accessible(self, client):
        shorten_resp = client.post("/api/shorten", json={"url": "https://example.com"})
        code = shorten_resp.json()["code"]
        client.delete(f"/api/{code}")
        resp = client.get(f"/{code}", follow_redirects=False)
        assert resp.status_code == 404

    def test_delete_unknown_code_returns_404(self, client):
        resp = client.delete("/api/zzzzzz")
        assert resp.status_code == 404
