from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class RunRequest(BaseModel):
    mode: str  # "battleroyale" | "stocks"
    bot_id: str
    code_hash: str
    code: Optional[str] = None  # optional on cache hit
    state: dict


class RunResponse(BaseModel):
    ok: bool
    action: Any
    error: Optional[str] = None
