from __future__ import annotations

import asyncio
import logging
import random
import uuid
from typing import Optional

from ..bot_interface import BotInterface
from ..config import Config, DEFAULT_CONFIG
from ..engine import GameEngine
from .schemas import GameInfo, GameStatus, make_tick_message, make_game_start_message, make_game_end_message
from .ws_manager import SpectatorManager

logger = logging.getLogger(__name__)


class GameSession:
    def __init__(
        self,
        game_id: str,
        spectator_manager: SpectatorManager,
        config: Config = DEFAULT_CONFIG,
        tick_interval: float = 0.1,
        seed: Optional[int] = None,
    ):
        self.game_id = game_id
        self._sm = spectator_manager
        self._cfg = config
        self.tick_interval = tick_interval
        self.seed = seed or random.randint(0, 2**31)

        self.status = GameStatus.WAITING
        self._bots: list[BotInterface] = []
        self._engine: Optional[GameEngine] = None
        self._task: Optional[asyncio.Task] = None
        self._last_snapshot: Optional[dict] = None

    def register_bot(self, bot: BotInterface) -> None:
        if self.status != GameStatus.WAITING:
            raise RuntimeError("게임이 이미 시작됐습니다.")
        self._bots.append(bot)

    def register_bots(self, bots: list[BotInterface]) -> None:
        for bot in bots:
            self.register_bot(bot)

    async def start(self) -> None:
        if len(self._bots) < self._cfg.game.min_bots:
            raise ValueError(f"최소 {self._cfg.game.min_bots}개의 봇이 필요합니다.")

        self._engine = GameEngine(self._bots, config=self._cfg, seed=self.seed)

        # Gemini 뉴스 사전 생성 (로딩 단계)
        self.status = GameStatus.LOADING
        logger.info("게임 로딩 중 (Gemini 뉴스 생성): %s", self.game_id)
        await asyncio.get_event_loop().run_in_executor(
            None, self._engine.market.pregenerate_news_batch, 20
        )

        self.status = GameStatus.RUNNING
        self._task = asyncio.create_task(self._run_loop())
        logger.info("게임 시작: %s (%d봇)", self.game_id, len(self._bots))

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.status = GameStatus.FINISHED

    def get_info(self) -> GameInfo:
        tick = self._engine.tick if self._engine else 0
        return GameInfo(
            game_id=self.game_id,
            status=self.status,
            current_tick=tick,
            total_bots=len(self._bots),
            bot_ids=[b.bot_id for b in self._bots],
        )

    def get_last_snapshot(self) -> Optional[dict]:
        return self._last_snapshot

    async def _run_loop(self) -> None:
        assert self._engine is not None
        try:
            await self._sm.broadcast(self.game_id, make_game_start_message(
                self.game_id, [b.bot_id for b in self._bots]
            ))

            while not self._engine.game_over:
                await asyncio.get_event_loop().run_in_executor(
                    None, self._engine.process_tick
                )
                snapshot = self._engine.snapshot()
                self._last_snapshot = snapshot
                await self._sm.broadcast(self.game_id, make_tick_message(self.game_id, snapshot))
                await asyncio.sleep(self.tick_interval)

            self.status = GameStatus.FINISHED
            result = self._engine.game_result
            await self._sm.broadcast(self.game_id, make_game_end_message(
                self.game_id, result.rankings if result else []
            ))
            logger.info("게임 종료: %s (틱 %d)", self.game_id, self._engine.tick)

        except asyncio.CancelledError:
            self.status = GameStatus.FINISHED
            logger.info("게임 %s 강제 중지", self.game_id)
            raise
        except Exception:
            self.status = GameStatus.ERROR
            logger.exception("게임 %s 오류", self.game_id)
            raise


class GameRegistry:
    def __init__(self, spectator_manager: SpectatorManager):
        self._sm = spectator_manager
        self._sessions: dict[str, GameSession] = {}

    def create_game(
        self,
        config: Config = DEFAULT_CONFIG,
        tick_interval: float = 0.1,
        seed: Optional[int] = None,
    ) -> GameSession:
        game_id = str(uuid.uuid4())[:8]
        session = GameSession(
            game_id=game_id,
            spectator_manager=self._sm,
            config=config,
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
