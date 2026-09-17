"""Runtime configuration, loaded from environment (see .env.example)."""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class Settings(BaseModel):
    ai_provider: str = "gemini"
    ai_model: str = "gemini-3.6-flash"
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    database_url: str = "sqlite:///./purchasing.db"
    autonomy_spend_limit_minor: int = 200_000
    autonomy_fee_limit_minor: int = 25_000
    max_tool_calls: int = 12
    max_replans: int = 2

    @property
    def has_llm_key(self) -> bool:
        key = self.gemini_api_key if self.ai_provider == "gemini" else self.anthropic_api_key
        return bool(key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        ai_provider=os.getenv("AI_PROVIDER", "gemini"),
        ai_model=os.getenv("AI_MODEL", "gemini-3.6-flash"),
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        database_url=os.getenv("DATABASE_URL", "sqlite:///./purchasing.db"),
        autonomy_spend_limit_minor=int(os.getenv("AUTONOMY_SPEND_LIMIT_MINOR", "200000")),
        autonomy_fee_limit_minor=int(os.getenv("AUTONOMY_FEE_LIMIT_MINOR", "25000")),
        max_tool_calls=int(os.getenv("MAX_TOOL_CALLS", "12")),
        max_replans=int(os.getenv("MAX_REPLANS", "2")),
    )
