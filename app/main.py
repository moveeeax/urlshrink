"""FastAPI application — URL shortener service."""

from typing import Optional

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from starlette.requests import Request

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
