"""Storage abstraction layer: BaseStorage interface + InMemoryStorage + SQLAlchemyStorage."""

import random
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from app.codec import CODE_LENGTH, encode, pad


class URLRecord:
    """Simple data class representing a stored URL entry."""

    def __init__(self, code: str, url: str, hits: int = 0,
                 created_at: Optional[datetime] = None):
        self.code = code
        self.url = url
        self.hits = hits
        self.created_at = created_at or datetime.utcnow()

    def to_dict(self) -> dict:
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

    def _generate_code(self) -> str:
        """Generate a random 6-char base62 code that is not yet in storage.

        Retries up to 10 times on collision (extremely unlikely with 62^6 > 56B space).
        """
        max_attempts = 10
        for attempt in range(max_attempts):
            n = random.randint(0, 62 ** CODE_LENGTH - 1)
            code = pad(encode(n))
            if self.get(code) is None:
                return code
        raise RuntimeError(
            f"Could not generate a unique short code after {max_attempts} attempts; "
            "storage may be saturated"
        )


class InMemoryStorage(BaseStorage):
    """Volatile in-memory storage — used by tests."""

    def __init__(self):
        self._store = {}  # code -> URLRecord

    def save(self, url: str, code: Optional[str] = None) -> URLRecord:
        if code is None:
            code = self._generate_code()
        record = URLRecord(code=code, url=url)
        self._store[code] = record
        return record

    def get(self, code: str) -> Optional[URLRecord]:
        return self._store.get(code)

    def increment_hits(self, code: str) -> None:
        record = self._store.get(code)
        if record is not None:
            record.hits += 1

    def delete(self, code: str) -> bool:
        if code in self._store:
            del self._store[code]
            return True
        return False


class SQLAlchemyStorage(BaseStorage):
    """SQLAlchemy-backed persistent storage."""

    def __init__(self, session_factory):
        # session_factory is a callable that returns a Session (e.g. SessionLocal)
        self._session_factory = session_factory

    def _to_record(self, entry) -> URLRecord:
        return URLRecord(
            code=entry.code,
            url=entry.url,
            hits=entry.hits,
            created_at=entry.created_at,
        )

    def save(self, url: str, code: Optional[str] = None) -> URLRecord:
        from app.models import URLEntry  # local import to avoid circular deps
        if code is None:
            code = self._generate_code()
        db = self._session_factory()
        try:
            entry = URLEntry(code=code, url=url)
            db.add(entry)
            db.commit()
            db.refresh(entry)
            return self._to_record(entry)
        finally:
            db.close()

    def get(self, code: str) -> Optional[URLRecord]:
        from app.models import URLEntry
        db = self._session_factory()
        try:
            entry = db.query(URLEntry).filter(URLEntry.code == code).first()
            return self._to_record(entry) if entry else None
        finally:
            db.close()

    def increment_hits(self, code: str) -> None:
        from app.models import URLEntry
        db = self._session_factory()
        try:
            db.query(URLEntry).filter(URLEntry.code == code).update(
                {URLEntry.hits: URLEntry.hits + 1}
            )
            db.commit()
        finally:
            db.close()

    def delete(self, code: str) -> bool:
        from app.models import URLEntry
        db = self._session_factory()
        try:
            entry = db.query(URLEntry).filter(URLEntry.code == code).first()
            if entry is None:
                return False
            db.delete(entry)
            db.commit()
            return True
        finally:
            db.close()
