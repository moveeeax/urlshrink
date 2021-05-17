"""FastAPI application — URL shortener service."""

from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
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
        raise HTTPException(status_code=404, detail="Code not found")
    return StatsResponse(**record.to_dict())


@app.get("/{code}")
def redirect_url(
    code: str,
    storage: BaseStorage = Depends(get_storage),
):
    record = storage.get(code)
    if record is None:
        raise HTTPException(status_code=404, detail="Code not found")
    storage.increment_hits(code)
    return RedirectResponse(url=record.url, status_code=307)
