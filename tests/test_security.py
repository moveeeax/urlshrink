"""Security regression tests.

Each case here corresponds to a way a URL shortener gets abused in the wild. If
one of these starts failing, the service has become a redirect gadget, an XSS
delivery mechanism, or an enumerable link directory.
"""

import random

import pytest
from fastapi.testclient import TestClient

from app.config import MAX_URL_LENGTH
from app.main import app
from app.storage import InMemoryStorage


@pytest.fixture(autouse=True)
def inject_memory_storage():
    storage = InMemoryStorage()
    app.state.storage = storage
    yield storage
    del app.state.storage


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Open redirect — scheme allow-list
# ---------------------------------------------------------------------------

class TestSchemeAllowList:
    """`javascript:`/`data:` stored in a shortener is stored XSS: the victim
    clicks a link on your domain and the payload runs. `file:` reaches local
    disk. None of them may ever be shortened."""

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "JavaScript:alert(1)",
            "  javascript:alert(1)  ",
            "javascript:/*--></title></style></script></textarea><svg/onload=alert(1)>",
            "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
            "data:text/html,<script>alert(1)</script>",
            "file:///etc/passwd",
            "file://localhost/etc/shadow",
            "vbscript:msgbox(1)",
            "ftp://example.com/f",
            "gopher://example.com/",
            "mailto:someone@example.com",
            "//example.com/protocol-relative",
            "/just/a/path",
            "not-a-url",
        ],
    )
    def test_dangerous_scheme_rejected(self, client, url):
        resp = client.post("/api/shorten", json={"url": url})
        assert resp.status_code == 422, f"{url!r} was accepted"

    @pytest.mark.parametrize(
        "url",
        [
            "http://example.com",
            "https://example.com",
            "HTTPS://example.com/Path?q=1#frag",
            "https://example.com:8443/path",
            "https://user-facing.example.co.uk/a/b?c=d&e=f",
        ],
    )
    def test_http_and_https_accepted(self, client, url):
        resp = client.post("/api/shorten", json={"url": url})
        assert resp.status_code == 201, f"{url!r} was rejected"

    def test_scheme_check_survives_tab_smuggling(self, client):
        """urlsplit() strips tabs/newlines before parsing, so `java\\tscript:`
        parses as the javascript scheme. Reject on the control character first."""
        resp = client.post("/api/shorten", json={"url": "java\tscript:alert(1)"})
        assert resp.status_code == 422


class TestHostRequired:
    @pytest.mark.parametrize("url", ["http://", "https://", "https:///path", "http://:80"])
    def test_url_without_host_rejected(self, client, url):
        resp = client.post("/api/shorten", json={"url": url})
        assert resp.status_code == 422

    def test_embedded_credentials_rejected(self, client):
        """`https://trusted.example@evil.example/` displays as the trusted host
        in many UIs but navigates to the attacker's."""
        resp = client.post(
            "/api/shorten", json={"url": "https://www.paypal.com@evil.example/login"}
        )
        assert resp.status_code == 422

    def test_invalid_port_rejected(self, client):
        resp = client.post("/api/shorten", json={"url": "https://example.com:99999/"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Header injection / response safety
# ---------------------------------------------------------------------------

class TestResponseSafety:
    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/\r\nSet-Cookie: sess=stolen",
            "https://example.com/\nLocation: https://evil.example",
            "https://example.com/\x00",
            "https://example.com/\x1b[2J",
        ],
    )
    def test_control_characters_rejected(self, client, url):
        resp = client.post("/api/shorten", json={"url": url})
        assert resp.status_code == 422, f"{url!r} was accepted"

    def test_location_header_has_no_raw_html_metacharacters(self, client):
        """The stored URL is echoed into the `Location` header. Even though the
        target is only ever a header (never an HTML sink), it must come back
        percent-encoded rather than raw."""
        hostile = 'https://example.com/?q="><script>alert(1)</script>'
        code = client.post("/api/shorten", json={"url": hostile}).json()["code"]

        resp = client.get(f"/{code}", follow_redirects=False)

        assert resp.status_code == 307
        location = resp.headers["location"]
        for char in ('"', "<", ">"):
            assert char not in location, f"{char!r} appears raw in Location: {location}"

    def test_errors_and_payloads_are_json_not_html(self, client):
        """There is no HTML template anywhere in the app, so a user-supplied URL
        can never land in an HTML context. Pin that: responses are JSON, and the
        URL comes back as a JSON string value."""
        hostile = "https://example.com/?q=<img src=x onerror=alert(1)>"
        code = client.post("/api/shorten", json={"url": hostile}).json()["code"]

        stats = client.get(f"/api/stats/{code}")
        assert stats.headers["content-type"].startswith("application/json")
        assert stats.json()["url"] == hostile

        missing = client.get("/api/stats/zzzzzz")
        assert missing.status_code == 404
        assert missing.headers["content-type"].startswith("application/json")

    def test_redirect_is_not_cacheable(self, client):
        """A cached redirect keeps working after the owner deletes the link."""
        code = client.post("/api/shorten", json={"url": "https://example.com"}).json()["code"]
        resp = client.get(f"/{code}", follow_redirects=False)
        assert resp.headers.get("cache-control") == "no-store"


# ---------------------------------------------------------------------------
# Resource bounds
# ---------------------------------------------------------------------------

class TestUrlLength:
    def test_url_at_limit_accepted(self, client):
        prefix = "https://example.com/"
        url = prefix + "a" * (MAX_URL_LENGTH - len(prefix))
        assert len(url) == MAX_URL_LENGTH
        assert client.post("/api/shorten", json={"url": url}).status_code == 201

    def test_oversized_url_rejected(self, client):
        """SQLite does not enforce VARCHAR(2048), so without an explicit check an
        anonymous caller can store megabytes per request."""
        url = "https://example.com/" + "a" * MAX_URL_LENGTH
        assert client.post("/api/shorten", json={"url": url}).status_code == 422

    def test_empty_and_whitespace_rejected(self, client):
        for url in ("", "   ", "\t\n"):
            assert client.post("/api/shorten", json={"url": url}).status_code == 422


# ---------------------------------------------------------------------------
# Short code unpredictability
# ---------------------------------------------------------------------------

class TestCodeUnpredictability:
    def test_codes_do_not_follow_the_random_module_seed(self):
        """Regression test for codes generated with `random`.

        `random` is a Mersenne Twister seeded from shared global state, so two
        runs with the same seed produce identical codes — which means an attacker
        who can observe or set the seed can enumerate every link ever issued.
        With a CSPRNG the two sequences are independent.
        """
        random.seed(1234)
        first = [InMemoryStorage()._generate_code() for _ in range(8)]
        random.seed(1234)
        second = [InMemoryStorage()._generate_code() for _ in range(8)]

        assert first != second

    def test_codes_are_well_formed_and_distinct(self):
        from app.codec import ALPHABET, CODE_LENGTH

        store = InMemoryStorage()
        codes = {store.save("https://example.com").code for _ in range(200)}

        assert len(codes) == 200, "generated codes collided"
        for code in codes:
            assert len(code) == CODE_LENGTH
            assert set(code) <= set(ALPHABET)
