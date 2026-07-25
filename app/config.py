import os


def _int_env(name: str, default: int) -> int:
    """Read a non-negative integer from the environment, falling back on *default*."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value < 0:
        raise ValueError(f"{name} must not be negative, got {value}")
    return value


DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///./urlshrink.db")
BASE_URL: str = os.environ.get("BASE_URL", "http://localhost:8000")

# Longest URL accepted by POST /api/shorten. Matches the `urls.url` column width.
# SQLite does not enforce VARCHAR limits, so without this check an unauthenticated
# caller could store arbitrarily large payloads.
MAX_URL_LENGTH: int = _int_env("MAX_URL_LENGTH", 2048)

# Rate limit applied to short-code creation, per client IP. Set
# RATE_LIMIT_REQUESTS=0 to disable the limiter entirely.
RATE_LIMIT_REQUESTS: int = _int_env("RATE_LIMIT_REQUESTS", 60)
RATE_LIMIT_WINDOW_SECONDS: int = _int_env("RATE_LIMIT_WINDOW_SECONDS", 60)
