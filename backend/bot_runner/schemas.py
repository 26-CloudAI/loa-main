from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class RunRequest(BaseModel):
    mode: str  # "battleroyale" | "battleroyale2" | "stocks"
    bot_id: str
    code_hash: str
    code: Optional[str] = None  # optional on cache hit
    state: dict
    phase: Optional[str] = None  # battleroyale2: "choose_spawn" | None(get_action)


class RunResponse(BaseModel):
    ok: bool
    action: Any
    error: Optional[str] = None
