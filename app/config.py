import os


DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///./urlshrink.db")
BASE_URL: str = os.environ.get("BASE_URL", "http://localhost:8000")
