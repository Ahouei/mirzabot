"""Central configuration (replaces config.php placeholders).

Loaded from environment / .env via pydantic-settings.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MIRZA_", extra="ignore")

    # ── Database ────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://mirza:mirza@localhost/mirza"
    db_echo: bool = False

    # ── Telegram bot ────────────────────────────────────────────
    api_key: str = ""                    # main bot token
    admin_number: int = 0                # primary admin Telegram id
    username_bot: str = ""               # bot username without @
    domain_hosts: str = "localhost"      # public https domain serving api/web/sub
    webhook_secret: str = ""             # X-Telegram-Bot-Api-Secret-Token
    webhook_path: str = "/webhook"
    use_polling: bool = False            # dev mode
    supergroup_id: int | None = None     # topics-based report chat

    # ── API surface ─────────────────────────────────────────────
    api_tokens_file: str = "hash.txt"    # extra tokens, mirrors legacy api/hash.txt
    session_secret: str = "change-me"    # web panel sessions / itsdangerous signing
    panel_secret: str = ""               # Fernet source for panel passwords;
                                         # falls back to session_secret when unset

    # ── Scheduler ───────────────────────────────────────────────
    timezone: str = "Asia/Tehran"

    # ── White-label ─────────────────────────────────────────────
    whitelabel_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
