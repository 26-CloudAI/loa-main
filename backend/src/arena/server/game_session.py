"""
AI Arena — 게임 세션 매니저

하나의 게임 세션을 관리한다:
  1. 봇 코드를 받아 BotInterface 목록을 생성
  2. 엔진을 생성하고 비동기 루프로 틱을 실행
  3. 매 틱마다 상태를 StateStore에 저장하고 PubSubBroker로 브로드캐스팅
  4. 게임 종료 시 결과 저장
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from typing import Optional

from ..bot_interface import BotInterface
from ..config import DEFAULT_CONFIG, GameConfig
from ..engine import GameEngine
from ..types import TickEvent
from .config import ServerConfig
from .redis_manager import PubSubBroker, StateStore
from .schemas import (
    EventBroadcast,
    GameInfo,
    GameResultResponse,
    GameStatus,
    TickBroadcast,
    make_game_end_message,
    make_game_start_message,
)

logger = logging.getLogger(__name__)


class GameSession:
    """
    하나의 게임 판을 나타낸다.

    라이프사이클:
      생성 → register_bot() → start() → (틱 루프) → 종료
    """

    def __init__(
        self,
        game_id: str,
        state_store: StateStore,
        pubsub: PubSubBroker,
        server_config: ServerConfig,
        game_config: GameConfig = DEFAULT_CONFIG,
        tick_interval: float = 0.05,
        seed: Optional[int] = None,
    ):
        self.game_id = game_id
        self.state_store = state_store
        self.pubsub = pubsub
        self.server_config = server_config
        self.game_config = game_config
        self.tick_interval = tick_interval
        self.seed = seed or random.randint(0, 2**31)

        self.status = GameStatus.WAITING
        self._bot_interfaces: list[BotInterface] = []
        self._engine: Optional[GameEngine] = None
        self._task: Optional[asyncio.Task] = None

    @property
    def tick_channel(self) -> str:
        return f"{self.server_config.redis.tick_channel_prefix}{self.game_id}"

    @property
    def event_channel(self) -> str:
        return f"{self.server_config.redis.event_channel_prefix}{self.game_id}"

    # ──────────────────────────────────────────────
    #  봇 등록
    # ──────────────────────────────────────────────

    def register_bot(self, bot: BotInterface) -> None:
        """봇 인터페이스를 등록한다."""
        if self.status != GameStatus.WAITING:
            raise RuntimeError(f"게임이 이미 {self.status.value} 상태입니다.")
        self._bot_interfaces.append(bot)

    def register_bots(self, bots: list[BotInterface]) -> None:
        for bot in bots:
            self.register_bot(bot)

    # ──────────────────────────────────────────────
    #  게임 실행
    # ──────────────────────────────────────────────

    async def start(self) -> None:
        """게임을 비동기 태스크로 시작한다."""
        if self.status != GameStatus.WAITING:
            raise RuntimeError(f"게임을 시작할 수 없는 상태: {self.status.value}")

        if len(self._bot_interfaces) < 2:
            raise ValueError("최소 2개의 봇이 필요합니다.")

        self._engine = GameEngine(
            self._bot_interfaces,
            config=self.game_config,
            seed=self.seed,
        )

        self.status = GameStatus.RUNNING
        self._task = asyncio.create_task(self._run_loop())
        logger.info("게임 시작: %s (%d봇)", self.game_id, len(self._bot_interfaces))

    async def stop(self) -> None:
        """게임을 강제 중지한다."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.status = GameStatus.FINISHED

    async def wait_until_done(self) -> None:
        """게임이 끝날 때까지 대기."""
        if self._task:
            await self._task

    # ──────────────────────────────────────────────
    #  정보 조회
    # ──────────────────────────────────────────────

    def get_info(self) -> GameInfo:
        alive = 0
        total = len(self._bot_interfaces)
        bot_ids = [b.bot_id for b in self._bot_interfaces]
        tick = 0

        if self._engine:
            alive = len(self._engine.get_alive_bots())
            tick = self._engine.tick

        return GameInfo(
            game_id=self.game_id,
            status=self.status,
            current_tick=tick,
            total_bots=total,
            alive_bots=alive,
            bot_ids=bot_ids,
        )

    # ──────────────────────────────────────────────
    #  내부 — 틱 루프
    # ──────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """메인 게임 루프. 각 틱을 처리하고 결과를 브로드캐스팅."""
        assert self._engine is not None

        try:
            # 게임 시작 알림
            start_msg = make_game_start_message(
                self.game_id,
                [b.bot_id for b in self._bot_interfaces],
            )
            await self.pubsub.publish(self.tick_channel, start_msg)

            while not self._engine.game_over:
                # 틱 처리 (동기 → asyncio에서 블로킹 방지)
                events = await asyncio.get_event_loop().run_in_executor(
                    None, self._engine.process_tick
                )

                # 상태 브로드캐스팅
                await self._broadcast_tick()

                # 이벤트 브로드캐스팅
                for event in events:
                    if event.event_type in ("kill", "mine_success", "death"):
                        await self._broadcast_event(event)

                # 틱 간격 대기 (관전 속도 제어)
                await asyncio.sleep(self.tick_interval)

            # 게임 종료 처리
            await self._handle_game_end()

        except asyncio.CancelledError:
            logger.info("게임 %s 강제 중지됨", self.game_id)
            self.status = GameStatus.FINISHED
            raise

        except Exception:
            logger.exception("게임 %s 오류 발생", self.game_id)
            self.status = GameStatus.ERROR
            raise

    async def _broadcast_tick(self) -> None:
        """현재 틱 상태를 저장하고 브로드캐스팅."""
        assert self._engine is not None

        # 봇 상태 수집
        bots_data = []
        for bot in self._engine.bots.values():
            bots_data.append({
                "id": bot.id,
                "x": bot.position.x,
                "y": bot.position.y,
                "energy": bot.energy,
                "score": round(bot.score, 1),
                "alive": bot.alive,
                "shield_active": bot.shield_active,
            })

        # 광물 위치
        minerals_data = [
            {"x": x, "y": y, "rare": rare}
            for x, y, rare in self._engine.grid.get_all_mineral_positions()
        ]

        # 리더보드
        alive_bots = sorted(
            [b for b in self._engine.bots.values() if b.alive],
            key=lambda b: b.score,
            reverse=True,
        )
        leaderboard = [
            {"rank": i + 1, "id": b.id, "score": round(b.score, 1)}
            for i, b in enumerate(alive_bots[:self._engine.config.leaderboard_size])
        ]

        tick_data = TickBroadcast(
            tick=self._engine.tick,
            bots=bots_data,
            minerals=minerals_data,
            zone_bounds=self._engine.zone.bounds,
            alive_count=len(alive_bots),
            leaderboard=leaderboard,
        )

        msg = tick_data.to_dict()

        # Redis 저장 + Pub/Sub 발행
        await self.state_store.save_game_state(self.game_id, msg["data"])
        await self.pubsub.publish(self.tick_channel, msg)

    async def _broadcast_event(self, event: TickEvent) -> None:
        """이벤트를 브로드캐스팅."""
        ev = EventBroadcast(
            tick=event.tick,
            event_type=event.event_type,
            actor_id=event.actor_id,
            target_id=event.target_id,
            detail=event.detail,
        )
        await self.pubsub.publish(self.event_channel, ev.to_dict())

    async def _handle_game_end(self) -> None:
        """게임 종료 시 결과 저장 및 알림."""
        assert self._engine is not None
        assert self._engine.game_result is not None

        result = self._engine.game_result
        self.status = GameStatus.FINISHED

        result_data = GameResultResponse(
            game_id=self.game_id,
            reason=result.reason.value,
            final_tick=result.final_tick,
            rankings=result.rankings,
        )

        # 결과 저장
        await self.state_store.save_game_result(self.game_id, result_data.to_dict())

        # 종료 메시지 브로드캐스팅
        end_msg = make_game_end_message(
            self.game_id, result.reason.value, result.rankings
        )
        await self.pubsub.publish(self.tick_channel, end_msg)

        logger.info(
            "게임 종료: %s — %s (틱 %d)",
            self.game_id, result.reason.value, result.final_tick,
        )


# ──────────────────────────────────────────────
#  게임 세션 레지스트리
# ──────────────────────────────────────────────

class GameRegistry:
    """
    활성 게임 세션들을 관리하는 레지스트리.
    API 핸들러에서 게임 생성/조회/삭제 시 사용.
    """

    def __init__(
        self,
        state_store: StateStore,
        pubsub: PubSubBroker,
        server_config: ServerConfig,
    ):
        self.state_store = state_store
        self.pubsub = pubsub
        self.server_config = server_config
        self._sessions: dict[str, GameSession] = {}

    def create_game(
        self,
        game_config: GameConfig = DEFAULT_CONFIG,
        tick_interval: float = 0.05,
        seed: Optional[int] = None,
    ) -> GameSession:
        """새 게임 세션을 생성한다."""
        game_id = str(uuid.uuid4())[:8]

        session = GameSession(
            game_id=game_id,
            state_store=self.state_store,
            pubsub=self.pubsub,
            server_config=self.server_config,
            game_config=game_config,
            tick_interval=tick_interval,
            seed=seed,
        )

        self._sessions[game_id] = session
        logger.info("게임 생성: %s", game_id)
        return session

    def get_game(self, game_id: str) -> Optional[GameSession]:
        return self._sessions.get(game_id)

    def list_games(self) -> list[GameInfo]:
        return [s.get_info() for s in self._sessions.values()]

    def remove_game(self, game_id: str) -> None:
        self._sessions.pop(game_id, None)

    async def cleanup_finished(self) -> int:
        """종료된 게임 세션을 정리. 제거된 수를 반환."""
        finished = [
            gid for gid, s in self._sessions.items()
            if s.status in (GameStatus.FINISHED, GameStatus.ERROR)
        ]
        for gid in finished:
            self._sessions.pop(gid, None)
        return len(finished)
