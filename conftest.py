# conftest.py — pytest configuration at project root.
# Ensures pytest discovers tests/app as packages correctly, and keeps the
# process-wide rate limiter from leaking state between test cases.

import pytest

from app.config import RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS
from app.main import app
from app.ratelimit import RateLimiter


@pytest.fixture(autouse=True)
def fresh_rate_limiter():
    """Give every test its own limiter.

    The limiter in app.main is module state shared by the whole process, so
    without this each test would inherit the request counts of the ones before
    it and the suite would start failing once it grew past the budget.
    """
    app.state.rate_limiter = RateLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)
    yield
    del app.state.rate_limiter
