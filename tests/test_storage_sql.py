"""Tests for the SQLAlchemy storage backend.

This is the backend the service actually runs on in production, but until now
only InMemoryStorage was covered — so the lookup path that touches the database
was never exercised by the suite at all.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.storage import SQLAlchemyStorage


@pytest.fixture
def store(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(bind=engine)
    yield SQLAlchemyStorage(sessionmaker(autocommit=False, autoflush=False, bind=engine))
    engine.dispose()


class TestRoundTrip:
    def test_save_and_get(self, store):
        record = store.save("https://example.com/a")
        fetched = store.get(record.code)
        assert fetched is not None
        assert fetched.url == "https://example.com/a"
        assert fetched.hits == 0
        assert fetched.created_at is not None

    def test_generated_code_is_well_formed(self, store):
        record = store.save("https://example.com")
        assert len(record.code) == 6

    def test_explicit_code_used(self, store):
        record = store.save("https://example.com", code="abc123")
        assert record.code == "abc123"
        assert store.get("abc123").url == "https://example.com"

    def test_get_unknown_returns_none(self, store):
        assert store.get("nosuch") is None

    def test_increment_hits_persists(self, store):
        store.save("https://example.com", code="abc123")
        store.increment_hits("abc123")
        store.increment_hits("abc123")
        assert store.get("abc123").hits == 2

    def test_increment_unknown_is_a_noop(self, store):
        store.increment_hits("nosuch")  # must not raise

    def test_delete(self, store):
        store.save("https://example.com", code="abc123")
        assert store.delete("abc123") is True
        assert store.get("abc123") is None
        assert store.delete("abc123") is False

    def test_generated_codes_are_distinct(self, store):
        codes = {store.save("https://example.com").code for _ in range(50)}
        assert len(codes) == 50


class TestSqlInjection:
    """The short code goes straight from the URL path into a database lookup.

    SQLAlchemy binds it as a parameter, so these payloads are matched as literal
    code strings and find nothing. If anyone ever swaps the ORM filter for string
    interpolation — `text(f"... WHERE code = '{code}'")` — these tests fail.
    """

    PAYLOADS = [
        "' OR '1'='1",
        "' OR 1=1 --",
        "abc123' OR '1'='1",
        "'; DROP TABLE urls; --",
        "' UNION SELECT code, url, hits, created_at, id FROM urls --",
        '" OR ""="',
        "%",
        "_",
    ]

    @pytest.fixture
    def populated(self, store):
        store.save("https://secret-one.example", code="abc123")
        store.save("https://secret-two.example", code="def456")
        return store

    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_get_does_not_leak_other_records(self, populated, payload):
        assert populated.get(payload) is None, f"{payload!r} matched a record"

    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_delete_does_not_destroy_other_records(self, populated, payload):
        assert populated.delete(payload) is False
        assert populated.get("abc123") is not None
        assert populated.get("def456") is not None

    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_increment_hits_does_not_touch_other_records(self, populated, payload):
        populated.increment_hits(payload)
        assert populated.get("abc123").hits == 0
        assert populated.get("def456").hits == 0

    def test_table_survives_a_drop_attempt(self, populated):
        populated.get("'; DROP TABLE urls; --")
        populated.delete("'; DROP TABLE urls; --")
        # The table is still queryable and still holds both rows.
        assert populated.get("abc123") is not None
        assert populated.get("def456") is not None

    def test_wildcards_are_matched_literally_not_as_like_patterns(self, populated):
        """Equality, not LIKE — `%` must not act as a wildcard."""
        assert populated.get("%") is None
        assert populated.get("abc%") is None
        assert populated.get("abc12_") is None

    def test_payload_can_be_stored_and_retrieved_verbatim(self, store):
        """Round-tripping the payload proves it is treated as data end to end."""
        payload = "' OR '1'='1"
        store.save("https://example.com", code=payload)
        assert store.get(payload).url == "https://example.com"
        assert store.get("abc123") is None


class TestSchema:
    def test_code_is_unique(self, store):
        from sqlalchemy.exc import IntegrityError

        store.save("https://example.com/one", code="dupdup")
        with pytest.raises(IntegrityError):
            store.save("https://example.com/two", code="dupdup")

    def test_rows_are_actually_committed(self, store, tmp_path):
        """Guards against a backend that only ever holds records in a session."""
        store.save("https://example.com", code="abc123")
        engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT code, url FROM urls")).fetchall()
        engine.dispose()
        assert rows == [("abc123", "https://example.com")]
