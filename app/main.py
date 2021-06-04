"""FastAPI application — URL shortener service."""

from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, validator
from starlette.requests import Request

from app.config import BASE_URL
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
# Request / response schemas
# ---------------------------------------------------------------------------

class ShortenRequest(BaseModel):
    url: str

    @validator("url")
    def url_must_be_http(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("URL must start with http:// or https://")
        try:
            from urllib.parse import urlparse
            parsed = urlparse(v)
            if not parsed.netloc:
                raise ValueError("URL has no host")
        except Exception as exc:
            raise ValueError(str(exc))
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

@app.post("/api/shorten", response_model=ShortenResponse, status_code=201)
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
    return None


@app.get("/{code}")
def redirect_url(
    code: str,
    storage: BaseStorage = Depends(get_storage),
):
    record = storage.get(code)
    if record is None:
        raise HTTPException(status_code=404, detail="Short code not found")
    storage.increment_hits(code)
    return RedirectResponse(url=record.url, status_code=307)
