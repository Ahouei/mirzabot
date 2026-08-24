"""Pytest config: isolate env for integration tests (no .env bleed)."""
import os

os.environ["MIRZA_DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
