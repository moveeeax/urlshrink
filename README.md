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
- Base62 6-character codes; collision-safe generation
- SQLite persistence by default; pluggable storage abstraction

## Requirements

- Python 3.9+
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

| Variable       | Default                    | Description                        |
|----------------|----------------------------|------------------------------------|
| `DATABASE_URL` | `sqlite:///./urlshrink.db` | SQLAlchemy connection string       |
| `BASE_URL`     | `http://localhost:8000`    | Public base URL used in responses  |

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

## Development / Testing

```bash
# Install dev deps (same requirements.txt)
pip install -r requirements.txt

# Run tests
pytest -v

# Or with make
make test
```

Tests use an in-memory storage backend — no database file is created.

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
│   └── storage.py    # Storage abstraction + implementations
├── tests/
│   ├── test_codec.py
│   ├── test_storage.py
│   └── test_api.py
├── .github/workflows/ci.yml
├── Makefile
├── requirements.txt
└── LICENSE
```

## License

MIT — see [LICENSE](LICENSE).
