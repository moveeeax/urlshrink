"""Tests for the in-memory storage implementation."""

import pytest

from app.storage import InMemoryStorage


@pytest.fixture
def store():
    return InMemoryStorage()


class TestSave:
    def test_returns_url_record(self, store):
        record = store.save("https://example.com")
        assert record.url == "https://example.com"
        assert record.code is not None
        assert len(record.code) == 6

    def test_code_is_retrievable(self, store):
        record = store.save("https://example.com")
        fetched = store.get(record.code)
        assert fetched is not None
        assert fetched.url == "https://example.com"

    def test_explicit_code_used(self, store):
        record = store.save("https://example.com", code="abc123")
        assert record.code == "abc123"
        assert store.get("abc123") is not None

    def test_hit_count_starts_at_zero(self, store):
        record = store.save("https://example.com")
        assert record.hits == 0


class TestGet:
    def test_returns_none_for_unknown(self, store):
        assert store.get("xxxxxx") is None

    def test_returns_record_for_known(self, store):
        store.save("https://example.com", code="aaaaaa")
        assert store.get("aaaaaa") is not None


class TestIncrementHits:
    def test_increments_by_one(self, store):
        store.save("https://example.com", code="aaaaaa")
        store.increment_hits("aaaaaa")
        assert store.get("aaaaaa").hits == 1

    def test_multiple_increments(self, store):
        store.save("https://example.com", code="bbbbbb")
        for _ in range(5):
            store.increment_hits("bbbbbb")
        assert store.get("bbbbbb").hits == 5

    def test_increment_unknown_code_noop(self, store):
        # Should not raise
        store.increment_hits("zzzzzz")


class TestDelete:
    def test_delete_existing_returns_true(self, store):
        store.save("https://example.com", code="cccccc")
        assert store.delete("cccccc") is True
        assert store.get("cccccc") is None

    def test_delete_missing_returns_false(self, store):
        assert store.delete("dddddd") is False

    def test_deleted_record_not_retrievable(self, store):
        store.save("https://example.com", code="eeeeee")
        store.delete("eeeeee")
        assert store.get("eeeeee") is None
