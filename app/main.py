"""FastAPI application — URL shortener service."""

from typing import Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, field_validator
from starlette.requests import Request

from app.config import (
    BASE_URL,
    MAX_URL_LENGTH,
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
)
from app.ratelimit import RateLimiter
from app.storage import BaseStorage, InMemoryStorage, SQLAlchemyStorage

app = FastAPI(title="urlshrink", version="0.1.0")

# ---------------------------------------------------------------------------
# Storage dependency
# ---------------------------------------------------------------------------

_storage: Optional[BaseStorage] = None


def _default_storage() -> BaseStorage:
    """Lazy-initialise the SQLAlchemy storage on first request."""
    global _storage
    if _storage is None:
        from app.db import SessionLocal, init_db
        init_db()
        _storage = SQLAlchemyStorage(SessionLocal)
    return _storage


def get_storage(request: Request) -> BaseStorage:
    """FastAPI dependency — allows tests to inject an alternative storage."""
    override = getattr(request.app.state, "storage", None)
    if override is not None:
        return override
    return _default_storage()


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

_rate_limiter = RateLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)


def get_rate_limiter(request: Request) -> RateLimiter:
    """FastAPI dependency — allows tests to inject an alternative limiter."""
    override = getattr(request.app.state, "rate_limiter", None)
    if override is not None:
        return override
    return _rate_limiter


def enforce_rate_limit(
    request: Request,
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> None:
    """Reject callers that have exceeded the creation budget for their address.

    The key is the peer address taken from the socket. ``X-Forwarded-For`` is
    intentionally ignored — it is trivially forged, so trusting it would let any
    caller sidestep the limit by varying one header. Deployments behind a trusted
    proxy should run the proxy with ``--forwarded-allow-ips`` (or terminate the
    limit at the proxy) rather than parsing the header here.
    """
    client_key = request.client.host if request.client else "unknown"
    allowed, retry_after = limiter.allow(client_key)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many short URLs created; try again later",
            headers={"Retry-After": str(retry_after)},
        )


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

# Only these two schemes may ever be redirected to. `javascript:` and `data:`
# execute in the origin of whatever page follows the link; `file:` reaches the
# victim's local disk. A shortener that stores them becomes a delivery mechanism
# for stored XSS, so the check is an allow-list, not a block-list.
ALLOWED_SCHEMES = frozenset({"http", "https"})


class ShortenRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("URL must not be empty")

        if len(v) > MAX_URL_LENGTH:
            raise ValueError(f"URL must be at most {MAX_URL_LENGTH} characters")

        # Control characters — CR/LF above all — must never reach the `Location`
        # header of a redirect. Starlette percent-encodes the header value, so
        # this is defence in depth, but it also stops `java\nscript:` style
        # smuggling past the scheme check below, since urlsplit() silently strips
        # tabs and newlines before parsing.
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in v):
            raise ValueError("URL must not contain control characters")

        try:
            parsed = urlparse(v)
        except ValueError as exc:
            raise ValueError(f"URL could not be parsed: {exc}") from exc

        if parsed.scheme.lower() not in ALLOWED_SCHEMES:
            raise ValueError("URL scheme must be http or https")

        if not parsed.netloc or not parsed.hostname:
            raise ValueError("URL has no host")

        # `https://trusted.example@evil.example/` renders as the trusted host in
        # a lot of UIs while navigating to the attacker's. Browsers have been
        # stripping these for years; there is no reason to shorten one.
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("URL must not embed credentials")

        # `.port` raises for a malformed or out-of-range port.
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError(f"URL has an invalid port: {exc}") from exc

        return v


class ShortenResponse(BaseModel):
    code: str
    short_url: str


class StatsResponse(BaseModel):
    code: str
    url: str
    hits: int
    created_at: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post(
    "/api/shorten",
    response_model=ShortenResponse,
    status_code=201,
    dependencies=[Depends(enforce_rate_limit)],
)
def shorten_url(
    body: ShortenRequest,
    storage: BaseStorage = Depends(get_storage),
):
    record = storage.save(body.url)
    return ShortenResponse(
        code=record.code,
        short_url=f"{BASE_URL}/{record.code}",
    )


@app.get("/api/stats/{code}", response_model=StatsResponse)
def get_stats(
    code: str,
    storage: BaseStorage = Depends(get_storage),
):
    record = storage.get(code)
    if record is None:
        raise HTTPException(status_code=404, detail="Short code not found")
    return StatsResponse(**record.to_dict())


@app.delete("/api/{code}", status_code=204)
def delete_url(
    code: str,
    storage: BaseStorage = Depends(get_storage),
):
    deleted = storage.delete(code)
    if not deleted:
        raise HTTPException(status_code=404, detail="Short code not found")


@app.get("/{code}")
def redirect_url(
    code: str,
    storage: BaseStorage = Depends(get_storage),
):
    record = storage.get(code)
    if record is None:
        raise HTTPException(status_code=404, detail="Short code not found")
    storage.increment_hits(code)
    # 307 is deliberate: it is a *temporary* redirect, so browsers and proxies do
    # not cache it by default. A 301 would be cached indefinitely, which would
    # both freeze the hit counter and keep sending users to a link long after its
    # owner deleted it. `no-store` makes that non-cacheability explicit for
    # intermediaries that are laxer than the spec.
    return RedirectResponse(
        url=record.url,
        status_code=307,
        headers={"Cache-Control": "no-store"},
    )
