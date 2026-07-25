"""Tests for the creation rate limiter — the unit, and its wiring into the API."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.ratelimit import RateLimiter
from app.storage import InMemoryStorage


class FakeClock:
    """Deterministic replacement for time.monotonic, so window expiry can be
    tested without sleeping."""

    def __init__(self, start: float = 1_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ---------------------------------------------------------------------------
# RateLimiter unit tests
# ---------------------------------------------------------------------------

class TestRateLimiterUnit:
    def test_allows_up_to_the_budget_then_refuses(self):
        limiter = RateLimiter(3, 60, time_source=FakeClock())
        assert [limiter.allow("1.2.3.4")[0] for _ in range(3)] == [True, True, True]
        allowed, retry_after = limiter.allow("1.2.3.4")
        assert allowed is False
        assert retry_after == 60

    def test_budget_is_per_key(self):
        limiter = RateLimiter(1, 60, time_source=FakeClock())
        assert limiter.allow("1.1.1.1")[0] is True
        assert limiter.allow("1.1.1.1")[0] is False
        # A different caller is unaffected.
        assert limiter.allow("2.2.2.2")[0] is True

    def test_window_slides(self):
        clock = FakeClock()
        limiter = RateLimiter(2, 60, time_source=clock)
        assert limiter.allow("k")[0] is True
        assert limiter.allow("k")[0] is True
        assert limiter.allow("k")[0] is False

        clock.advance(61)
        assert limiter.allow("k")[0] is True, "calls should expire out of the window"

    def test_retry_after_counts_down_with_the_oldest_call(self):
        clock = FakeClock()
        limiter = RateLimiter(1, 60, time_source=clock)
        limiter.allow("k")
        clock.advance(45)
        allowed, retry_after = limiter.allow("k")
        assert allowed is False
        assert retry_after == 15

    def test_retry_after_is_never_zero_while_refusing(self):
        clock = FakeClock()
        limiter = RateLimiter(1, 60, time_source=clock)
        limiter.allow("k")
        clock.advance(59.9)
        allowed, retry_after = limiter.allow("k")
        assert allowed is False
        assert retry_after >= 1, "Retry-After: 0 would invite an immediate retry"

    @pytest.mark.parametrize("max_requests,window", [(0, 60), (60, 0), (0, 0)])
    def test_non_positive_settings_disable_the_limiter(self, max_requests, window):
        limiter = RateLimiter(max_requests, window, time_source=FakeClock())
        assert limiter.enabled is False
        assert all(limiter.allow("k")[0] for _ in range(500))

    def test_key_table_is_bounded(self):
        """The limiter's own bookkeeping must not become a memory-exhaustion
        vector when it sees a large number of distinct clients."""
        limiter = RateLimiter(5, 60, max_tracked_keys=32, time_source=FakeClock())
        for i in range(5_000):
            limiter.allow(f"10.0.{i // 256}.{i % 256}")
        assert len(limiter._hits) <= 32

    def test_stale_keys_are_pruned(self):
        clock = FakeClock()
        limiter = RateLimiter(5, 60, time_source=clock)
        for i in range(50):
            limiter.allow(f"key-{i}")
        assert len(limiter._hits) == 50

        clock.advance(3_600)
        limiter.allow("someone-new")
        assert len(limiter._hits) == 1, "keys idle for a whole window should be dropped"

    def test_reset_clears_state(self):
        limiter = RateLimiter(1, 60, time_source=FakeClock())
        assert limiter.allow("k")[0] is True
        assert limiter.allow("k")[0] is False
        limiter.reset()
        assert limiter.allow("k")[0] is True


# ---------------------------------------------------------------------------
# API wiring
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def inject_memory_storage():
    app.state.storage = InMemoryStorage()
    yield
    del app.state.storage


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=True)


class TestShortenIsRateLimited:
    def test_creation_is_throttled_with_429_and_retry_after(self, client):
        app.state.rate_limiter = RateLimiter(3, 60, time_source=FakeClock())

        for _ in range(3):
            assert client.post("/api/shorten", json={"url": "https://example.com"}).status_code == 201

        resp = client.post("/api/shorten", json={"url": "https://example.com"})
        assert resp.status_code == 429
        assert resp.headers["retry-after"] == "60"

    def test_rejected_requests_still_consume_budget(self, client):
        """Otherwise the limit is trivially bypassed by sending invalid bodies —
        the server does the parsing work either way."""
        app.state.rate_limiter = RateLimiter(2, 60, time_source=FakeClock())

        assert client.post("/api/shorten", json={"url": "ftp://example.com"}).status_code == 422
        assert client.post("/api/shorten", json={}).status_code == 422
        assert client.post("/api/shorten", json={"url": "https://example.com"}).status_code == 429

    def test_reads_and_deletes_are_not_throttled(self, client):
        """Only creation writes to storage; throttling lookups would break the
        product for popular links."""
        code = client.post("/api/shorten", json={"url": "https://example.com"}).json()["code"]
        app.state.rate_limiter = RateLimiter(1, 60, time_source=FakeClock())
        app.state.rate_limiter.allow("testclient")  # budget already spent

        for _ in range(5):
            assert client.get(f"/{code}", follow_redirects=False).status_code == 307
            assert client.get(f"/api/stats/{code}").status_code == 200
        assert client.delete(f"/api/{code}").status_code == 204

    def test_forwarded_for_header_cannot_bypass_the_limit(self, client):
        """X-Forwarded-For is attacker-controlled. Keying on it would make the
        limiter a no-op for anyone willing to send a header."""
        app.state.rate_limiter = RateLimiter(2, 60, time_source=FakeClock())

        for _ in range(2):
            client.post("/api/shorten", json={"url": "https://example.com"})

        resp = client.post(
            "/api/shorten",
            json={"url": "https://example.com"},
            headers={"X-Forwarded-For": "9.9.9.9", "X-Real-IP": "9.9.9.9"},
        )
        assert resp.status_code == 429

    def test_limiter_is_configurable_off(self, client):
        app.state.rate_limiter = RateLimiter(0, 60, time_source=FakeClock())
        for _ in range(25):
            assert client.post("/api/shorten", json={"url": "https://example.com"}).status_code == 201
