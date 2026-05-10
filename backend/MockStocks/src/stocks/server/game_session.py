from __future__ import annotations

import asyncio
import logging
import random
import uuid
from typing import TYPE_CHECKING, Optional

from ..bot_interface import BotInterface
from ..config import Config, DEFAULT_CONFIG
from ..engine import GameEngine
from .schemas import GameInfo, GameStatus, make_tick_message, make_game_start_message, make_game_end_message
from .ws_manager import SpectatorManager

if TYPE_CHECKING:
    from ..db.game_repo import StockGameRepository

logger = logging.getLogger(__name__)


class GameSession:
    def __init__(
        self,
        game_id: str,
        spectator_manager: SpectatorManager,
        config: Config = DEFAULT_CONFIG,
        tick_interval: float = 0.1,
        seed: Optional[int] = None,
        repo: Optional[StockGameRepository] = None,
        owner_uid: Optional[str] = None,
        name: Optional[str] = None,
    ):
        self.game_id = game_id
        self._sm = spectator_manager
        self._cfg = config
        self.tick_interval = tick_interval
        self.seed = seed or random.randint(0, 2**31)
        self._repo = repo
        self.owner_uid = owner_uid
        self.name = name

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

    async def start(self, prepared_news: list | None = None) -> None:
        if len(self._bots) < self._cfg.game.min_bots:
            raise ValueError(f"최소 {self._cfg.game.min_bots}개의 봇이 필요합니다.")

        if self._repo:
            self._repo.create_game(
                game_id=self.game_id,
                total_bots=len(self._bots),
                seed=self.seed,
                total_ticks=self._cfg.game.total_ticks,
                tick_interval=self.tick_interval,
                owner_uid=self.owner_uid,
                name=self.name,
            )
            for bot in self._bots:
                self._repo.add_participant(
                    game_id=self.game_id,
                    bot_id=bot.bot_id,
                    bot_name=bot.bot_id,
                    is_ai_filler=bot.is_ai_filler,
                )
            self._repo.update_game_started(self.game_id)

        self._engine = GameEngine(self._bots, config=self._cfg, seed=self.seed)

        if prepared_news:
            # 프론트에서 사전 생성된 뉴스 주입 → 즉시 시작
            self._engine.market._news_queue = list(prepared_news)
            logger.info("사전 생성 뉴스 %d개 주입: %s", len(prepared_news), self.game_id)
        else:
            # 폴백: 게임 시작 직전 생성 (Gemini 키 없으면 템플릿 사용)
            self.status = GameStatus.LOADING
            await asyncio.get_event_loop().run_in_executor(
                None, self._engine.market.pregenerate_news_batch, 20
            )

        self.status = GameStatus.RUNNING
        self._task = asyncio.create_task(self._run_loop())
        logger.info("게임 시작: %s (%d봇)", self.game_id, len(self._bots))

    async def stop(self) -> None:
        should_mark_cancelled = self.status in {
            GameStatus.WAITING,
            GameStatus.LOADING,
            GameStatus.RUNNING,
        }
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.status = GameStatus.FINISHED
        if self._repo and should_mark_cancelled:
            final_tick = self._engine.tick if self._engine else 0
            try:
                self._repo.update_game_finished(
                    game_id=self.game_id,
                    final_tick=final_tick,
                    end_reason="cancelled",
                )
            except Exception:
                logger.exception("게임 %s DB 중단 상태 저장 실패", self.game_id)

    def get_info(self) -> GameInfo:
        tick = self._engine.tick if self._engine else 0
        return GameInfo(
            game_id=self.game_id,
            status=self.status,
            current_tick=tick,
            total_bots=len(self._bots),
            bot_ids=[b.bot_id for b in self._bots],
            name=self.name,
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
            rankings = result.rankings if result else []

            if self._repo and result:
                try:
                    self._repo.update_game_finished(
                        game_id=self.game_id,
                        final_tick=result.final_tick,
                        end_reason="finished",
                    )
                    initial_cash = self._cfg.game.starting_cash
                    for entry in rankings:
                        final_value = entry["total_value"]
                        profit_rate = (final_value - initial_cash) / initial_cash * 100
                        self._repo.update_participant_result(
                            game_id=self.game_id,
                            bot_id=entry["id"],
                            final_rank=entry["rank"],
                            initial_cash=initial_cash,
                            final_total_value=final_value,
                            profit_rate=profit_rate,
                            final_credit_score=entry["credit_score"],
                        )
                except Exception:
                    logger.exception("게임 %s DB 종료 저장 실패", self.game_id)

            await self._sm.broadcast(self.game_id, make_game_end_message(
                self.game_id, rankings
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
    def __init__(
        self,
        spectator_manager: SpectatorManager,
        repo: Optional[StockGameRepository] = None,
    ):
        self._sm = spectator_manager
        self._sessions: dict[str, GameSession] = {}
        self._repo = repo

    def create_game(
        self,
        config: Config = DEFAULT_CONFIG,
        tick_interval: float = 0.1,
        seed: Optional[int] = None,
        owner_uid: Optional[str] = None,
        name: Optional[str] = None,
    ) -> GameSession:
        game_id = str(uuid.uuid4())[:8]
        session = GameSession(
            game_id=game_id,
            spectator_manager=self._sm,
            config=config,
            tick_interval=tick_interval,
            seed=seed,
            repo=self._repo,
            owner_uid=owner_uid,
            name=name,
        )
        self._sessions[game_id] = session
        logger.info("게임 생성: %s", game_id)
        return session

    def get_game(self, game_id: str) -> Optional[GameSession]:
        return self._sessions.get(game_id)

    def list_games(self, owner_uid: Optional[str] = None) -> list[GameInfo]:
        sessions = self._sessions.values()
        if owner_uid is not None:
            sessions = [s for s in sessions if s.owner_uid == owner_uid]
        return [s.get_info() for s in sessions]

    def remove_game(self, game_id: str) -> None:
        self._sessions.pop(game_id, None)
