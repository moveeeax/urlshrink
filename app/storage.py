"""Storage abstraction for the URL shortener."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional


class URLRecord:
    """Simple data class representing a stored URL entry."""

    def __init__(self, code: str, url: str, hits: int = 0,
                 created_at: Optional[datetime] = None):
        self.code = code
        self.url = url
        self.hits = hits
        self.created_at = created_at or datetime.utcnow()

    def to_dict(self):
        return {
            "code": self.code,
            "url": self.url,
            "hits": self.hits,
            "created_at": self.created_at.isoformat(),
        }


class BaseStorage(ABC):
    """Abstract base class defining the storage interface."""

    @abstractmethod
    def save(self, url: str, code: Optional[str] = None) -> URLRecord:
        """Persist a URL and return its record (with generated or given code)."""

    @abstractmethod
    def get(self, code: str) -> Optional[URLRecord]:
        """Return the URLRecord for *code*, or None if not found."""

    @abstractmethod
    def increment_hits(self, code: str) -> None:
        """Increment the hit counter for *code*."""

    @abstractmethod
    def delete(self, code: str) -> bool:
        """Delete the record for *code*. Return True if it existed."""
