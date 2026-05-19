from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class SpectatorManager:
    """게임별 WebSocket 관전 클라이언트 관리."""

    def __init__(self):
        # game_id → set of websocket objects
        self._spectators: dict[str, set] = {}

    async def connect(self, game_id: str, ws) -> None:
        await ws.accept()
        self._spectators.setdefault(game_id, set()).add(ws)
        logger.info("관전자 연결: 게임 %s (총 %d명)", game_id, len(self._spectators[game_id]))

    def disconnect(self, game_id: str, ws) -> None:
        if game_id in self._spectators:
            self._spectators[game_id].discard(ws)
        logger.info("관전자 해제: 게임 %s", game_id)

    async def broadcast(self, game_id: str, message: dict) -> None:
        dead = set()
        for ws in self._spectators.get(game_id, set()):
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._spectators[game_id].discard(ws)

    def count(self, game_id: str) -> int:
        return len(self._spectators.get(game_id, set()))
