"""
AI Arena — WebSocket 관전 매니저

관전 클라이언트의 연결을 관리하고,
Redis Pub/Sub에서 수신한 메시지를 모든 연결된 클라이언트에 전달한다.

설계 원칙:
  - 느린 클라이언트가 전체 브로드캐스팅을 지연시키지 않도록 per-client 큐 사용
  - 연결/해제 시 안전한 정리 보장
  - 게임별 구독자 그룹 분리
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

from .config import WebSocketConfig
from .redis_manager import PubSubBroker

logger = logging.getLogger(__name__)


class SpectatorConnection:
    """단일 WebSocket 관전 클라이언트."""

    def __init__(
        self,
        ws,  # WebSocket 객체 (FastAPI/Starlette)
        client_id: str,
        config: WebSocketConfig,
    ):
        self.ws = ws
        self.client_id = client_id
        self.config = config
        self.connected_at = time.monotonic()
        self.messages_sent = 0
        self.messages_dropped = 0

        self._queue: asyncio.Queue = asyncio.Queue(
            maxsize=config.client_queue_size
        )
        self._send_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """메시지 전송 태스크를 시작한다."""
        self._send_task = asyncio.create_task(self._send_loop())

    async def stop(self) -> None:
        """전송 태스크를 정지한다."""
        if self._send_task and not self._send_task.done():
            self._send_task.cancel()
            try:
                await self._send_task
            except asyncio.CancelledError:
                pass

    def enqueue(self, message: dict) -> None:
        """메시지를 큐에 넣는다. 큐가 가득 차면 오래된 메시지 드롭."""
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
                self.messages_dropped += 1
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(message)
            except asyncio.QueueFull:
                self.messages_dropped += 1

    async def _send_loop(self) -> None:
        """큐에서 메시지를 꺼내 WebSocket으로 전송."""
        try:
            while True:
                message = await self._queue.get()
                try:
                    await self.ws.send_json(message)
                    self.messages_sent += 1
                except Exception:
                    logger.debug(
                        "클라이언트 %s 전송 실패", self.client_id, exc_info=True,
                    )
                    break
        except asyncio.CancelledError:
            pass


class SpectatorManager:
    """
    게임별 관전 클라이언트 그룹을 관리한다.

    흐름:
      1. 클라이언트가 WebSocket 연결 → add_spectator()
      2. Redis Pub/Sub 리스너가 메시지 수신 → broadcast_to_game()
      3. 각 SpectatorConnection이 per-client 큐를 통해 전송
      4. 클라이언트 연결 해제 → remove_spectator()
    """

    def __init__(self, config: WebSocketConfig, pubsub: PubSubBroker):
        self.config = config
        self.pubsub = pubsub

        # game_id → {client_id → SpectatorConnection}
        self._spectators: dict[str, dict[str, SpectatorConnection]] = {}

        # game_id → Redis 구독 태스크
        self._sub_tasks: dict[str, asyncio.Task] = {}

        self._total_connections = 0
        self._next_client_id = 0

    # ──────────────────────────────────────────────
    #  공개 API
    # ──────────────────────────────────────────────

    async def add_spectator(self, game_id: str, ws) -> SpectatorConnection:
        """
        관전 클라이언트를 게임에 추가한다.
        반환된 SpectatorConnection을 통해 이후 제거.
        """
        # 연결 수 제한 체크
        game_spectators = self._spectators.get(game_id, {})
        if len(game_spectators) >= self.config.max_connections_per_game:
            raise ConnectionRefusedError(
                f"게임 {game_id}의 관전 인원이 최대입니다 "
                f"({self.config.max_connections_per_game}명)"
            )
        if self._total_connections >= self.config.max_total_connections:
            raise ConnectionRefusedError("서버 전체 연결 수 초과")

        # 클라이언트 등록
        self._next_client_id += 1
        client_id = f"spec_{self._next_client_id}"

        conn = SpectatorConnection(ws, client_id, self.config)
        await conn.start()

        if game_id not in self._spectators:
            self._spectators[game_id] = {}
        self._spectators[game_id][client_id] = conn
        self._total_connections += 1

        # 첫 번째 관전자면 Redis 구독 시작
        if game_id not in self._sub_tasks:
            self._sub_tasks[game_id] = asyncio.create_task(
                self._subscribe_loop(game_id)
            )

        logger.info(
            "관전자 추가: %s → 게임 %s (총 %d명)",
            client_id, game_id, len(self._spectators[game_id]),
        )
        return conn

    async def remove_spectator(
        self, game_id: str, conn: SpectatorConnection
    ) -> None:
        """관전 클라이언트를 제거한다."""
        await conn.stop()

        game_spectators = self._spectators.get(game_id, {})
        game_spectators.pop(conn.client_id, None)
        self._total_connections = max(0, self._total_connections - 1)

        # 관전자가 없으면 구독 해제
        if not game_spectators:
            self._spectators.pop(game_id, None)
            task = self._sub_tasks.pop(game_id, None)
            if task and not task.done():
                task.cancel()

        logger.info(
            "관전자 제거: %s (게임 %s, 남은 %d명)",
            conn.client_id, game_id, len(game_spectators),
        )

    def broadcast_to_game(self, game_id: str, message: dict) -> None:
        """게임의 모든 관전 클라이언트에게 메시지 전달 (인메모리 직접 전달)."""
        for conn in self._spectators.get(game_id, {}).values():
            conn.enqueue(message)

    def get_spectator_count(self, game_id: str) -> int:
        return len(self._spectators.get(game_id, {}))

    def get_total_connections(self) -> int:
        return self._total_connections

    async def cleanup(self) -> None:
        """모든 연결과 구독을 정리."""
        for game_id, spectators in list(self._spectators.items()):
            for conn in spectators.values():
                await conn.stop()

        for task in self._sub_tasks.values():
            if not task.done():
                task.cancel()

        self._spectators.clear()
        self._sub_tasks.clear()
        self._total_connections = 0

    # ──────────────────────────────────────────────
    #  내부 — Redis 구독 루프
    # ──────────────────────────────────────────────

    async def _subscribe_loop(self, game_id: str) -> None:
        """Redis Pub/Sub에서 메시지를 수신하여 관전자에게 전달."""
        channel = f"arena:tick:{game_id}"

        try:
            async for message in self.pubsub.subscribe(channel):
                self.broadcast_to_game(game_id, message)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Redis 구독 오류: 게임 %s", game_id)
