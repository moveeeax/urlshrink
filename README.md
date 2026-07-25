# urlshrink

A lightweight URL-shortener HTTP API built with FastAPI and SQLite. Generates
Base62 short codes, tracks redirect hit counts, and exposes a small REST
interface.

## Features

- `POST /api/shorten` — shorten any `http://` or `https://` URL
- `GET /{code}` — 307 redirect to the original URL (increments hit counter)
- `GET /api/stats/{code}` — retrieve code, original URL, hit count, creation
  timestamp
- `DELETE /api/{code}` — remove a short URL
- Base62 6-character codes drawn from a cryptographically secure RNG
- Per-IP rate limiting on short-code creation
- SQLite persistence by default; pluggable storage abstraction

## Requirements

- Python 3.10+
- pip

## Install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

By default the server listens on `http://localhost:8000` and stores data in
`urlshrink.db` (SQLite, created automatically).

### Configuration

| Variable                    | Default                    | Description                                                        |
|-----------------------------|----------------------------|--------------------------------------------------------------------|
| `DATABASE_URL`              | `sqlite:///./urlshrink.db` | SQLAlchemy connection string                                        |
| `BASE_URL`                  | `http://localhost:8000`    | Public base URL used in responses                                   |
| `MAX_URL_LENGTH`            | `2048`                     | Longest URL accepted by `POST /api/shorten`                         |
| `RATE_LIMIT_REQUESTS`       | `60`                       | Short URLs one client IP may create per window; `0` disables        |
| `RATE_LIMIT_WINDOW_SECONDS` | `60`                       | Length of the rate-limit window, in seconds                         |

## Endpoints

### Shorten a URL

```bash
curl -s -X POST http://localhost:8000/api/shorten \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://www.example.com/some/long/path"}' | python3 -m json.tool
```

Response (201):
```json
{
  "code": "aB3xYz",
  "short_url": "http://localhost:8000/aB3xYz"
}
```

### Redirect

```bash
curl -v http://localhost:8000/aB3xYz
```

Returns HTTP 307 to the original URL.

### Stats

```bash
curl -s http://localhost:8000/api/stats/aB3xYz | python3 -m json.tool
```

Response (200):
```json
{
  "code": "aB3xYz",
  "url": "https://www.example.com/some/long/path",
  "hits": 3,
  "created_at": "2021-06-15T10:23:00.123456"
}
```

### Delete

```bash
curl -X DELETE http://localhost:8000/api/aB3xYz
```

Returns HTTP 204 on success, 404 if not found.

## Security model

What the service guarantees, and what it deliberately leaves to the deployment.

**URL validation.** `POST /api/shorten` accepts a URL only if it passes every
check below; anything else is a `422`.

- The scheme is `http` or `https`, compared case-insensitively against an
  allow-list. `javascript:`, `data:`, `file:`, `vbscript:` and friends are
  refused — stored in a shortener they turn a link on your domain into stored
  XSS or local-file access.
- No control characters anywhere in the URL. This blocks CR/LF response-header
  smuggling, and it also closes `java&#9;script:`-style evasion, since
  `urlsplit()` silently strips tabs and newlines before the scheme is parsed.
- A host is present, the port (if any) is valid, and no credentials are embedded.
  `https://www.example.com@evil.example/` displays as the trusted host in many
  UIs while navigating somewhere else.
- The URL is at most `MAX_URL_LENGTH` characters. SQLite does not enforce
  `VARCHAR(2048)`, so without this an anonymous caller could store arbitrarily
  large payloads.

**Short codes** come from `secrets` (a CSPRNG), never `random`. A Mersenne
Twister leaks its internal state after a few hundred observed outputs, which
would let anyone reconstruct every code the process has issued — and a code is
the only thing protecting a link.

**Rate limiting.** Creation is capped per client IP (see the configuration
table); exceeding it returns `429` with a `Retry-After` header. The key is the
peer address from the socket — `X-Forwarded-For` is ignored on purpose, since
honouring it would let any caller bypass the limit with one extra header. The
counter lives in the process, so behind N workers or replicas the effective
budget is N x the limit; put a shared limiter in your ingress if that matters.

**Redirects** use 307 (temporary) and set `Cache-Control: no-store`, so a
redirect is not cached and a deleted link stops working immediately.

**SQL** is issued exclusively through SQLAlchemy's expression API, so the short
code from the URL path is always a bound parameter. `tests/test_storage_sql.py`
pins this with injection payloads.

Not in scope, by design: there is no authentication, so anyone who can reach the
API can create and delete links — put it behind your own authn/authz if that is
not acceptable. Link targets are not fetched or scanned, and private/loopback
and link-local addresses are **not** blocked, so the service can be used to
redirect to internal hosts. Add a host allow-list if you expose it publicly.

## Development / Testing

```bash
# Install dev deps (same requirements.txt)
pip install -r requirements.txt

# Run tests
pytest -v

# Or with make
make test
```

API tests use the in-memory storage backend. The SQLAlchemy backend is covered
separately against a throwaway SQLite file in pytest's `tmp_path`, so no database
file is created in the working tree.

## Project layout

```
urlshrink/
├── app/
│   ├── __init__.py
│   ├── codec.py      # Base62 encode/decode
│   ├── config.py     # Environment-based configuration
│   ├── db.py         # SQLAlchemy engine & session
│   ├── main.py       # FastAPI app + routes
│   ├── models.py     # ORM model
│   ├── ratelimit.py  # In-process sliding-window rate limiter
│   └── storage.py    # Storage abstraction + implementations
├── tests/
│   ├── test_codec.py
│   ├── test_storage.py
│   ├── test_storage_sql.py
│   ├── test_ratelimit.py
│   ├── test_security.py
│   └── test_api.py
├── .github/workflows/ci.yml
├── Makefile
├── requirements.txt
└── LICENSE
```

## License

MIT — see [LICENSE](LICENSE).
