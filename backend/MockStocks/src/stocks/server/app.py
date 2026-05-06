"""
MockStocks — FastAPI 서버

엔드포인트:
  POST /api/stocks/prepare      뉴스 사전 생성 (게임 코드 페이지 진입 시)
  GET  /api/stocks/prepare/{id} 준비 상태 확인
  POST /api/games               게임 생성 + 시작
  GET  /api/games               활성 게임 목록
  GET  /api/games/{id}          게임 정보
  GET  /api/games/{id}/result   게임 결과
  DELETE /api/games/{id}        게임 강제 종료
  WS   /ws/games/{id}           실시간 관전
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..bot_interface import BotInterface
from ..config import Config, DEFAULT_CONFIG
from ..market import Market
from .game_session import GameRegistry
from .ws_manager import SpectatorManager


class BotSubmission(BaseModel):
    bot_id: str
    code: str

class CreateGameRequest(BaseModel):
    bots: list[BotSubmission] = []
    fill_with_ai: bool = True
    min_bots: int = 4
    tick_interval: float = 0.1
    seed: Optional[int] = None
    prepare_id: Optional[str] = None  # 사전 생성된 뉴스 ID

logger = logging.getLogger(__name__)


# ── InProcessBot ──────────────────────────────────────────────────────────────

class InProcessBot(BotInterface):
    """유저 제출 코드를 실행하는 어댑터."""

    def __init__(self, bot_id: str, code: str):
        super().__init__(bot_id)
        self._action_fn = None
        self._load_error: Optional[str] = None
        try:
            ns: dict = {"__builtins__": __builtins__}
            exec(code, ns)
            fn = ns.get("action")
            if fn is None or not callable(fn):
                raise ValueError("action(state) 함수를 찾을 수 없습니다.")
            self._action_fn = fn
        except Exception as e:
            self._load_error = str(e)
            logger.warning("봇 %s 로드 실패: %s", bot_id, e)

    def get_action(self, state: dict) -> dict:
        if self._action_fn is None:
            return {"action": "HOLD"}
        try:
            result = self._action_fn(state)
            if isinstance(result, dict):
                return result
            return {"action": "HOLD"}
        except Exception:
            return {"action": "HOLD"}


# ── 더미 AI 봇 ────────────────────────────────────────────────────────────────

class RandomBot(BotInterface):
    """랜덤 매매 AI (테스트용 filler)."""

    import random as _r

    def get_action(self, state: dict) -> dict:
        import random
        stocks = state["market"]["stocks"]
        my = state["my_bot"]
        stock = random.choice(stocks)
        action = random.choice(["BUY", "SELL", "HOLD", "HOLD"])

        if action == "BUY" and my["cash"] >= stock["price"]:
            qty = max(1, int(my["cash"] * 0.1 / stock["price"]))
            return {"action": "BUY", "symbol": stock["symbol"], "quantity": qty}

        if action == "SELL" and my["portfolio"].get(stock["symbol"], 0) > 0:
            qty = max(1, my["portfolio"][stock["symbol"]] // 2)
            return {"action": "SELL", "symbol": stock["symbol"], "quantity": qty}

        return {"action": "HOLD"}


# ── FastAPI 앱 ────────────────────────────────────────────────────────────────

def create_app(config: Config = DEFAULT_CONFIG) -> FastAPI:
    app = FastAPI(title="MockStocks API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    spectator_manager = SpectatorManager()
    registry = GameRegistry(spectator_manager)

    # prepare_id → 사전 생성된 뉴스 큐 (None = 아직 생성 중)
    _prepared_news: dict[str, list | None] = {}

    # ── 뉴스 사전 생성 ──────────────────────────────────────────────────────────

    @app.post("/api/stocks/prepare")
    async def prepare_news():
        prepare_id = str(uuid.uuid4())[:8]
        _prepared_news[prepare_id] = None  # 생성 중 표시

        async def _do_prepare():
            market = Market(DEFAULT_CONFIG)
            await asyncio.get_event_loop().run_in_executor(
                None, market.pregenerate_news_batch, 20
            )
            _prepared_news[prepare_id] = market._news_queue
            logger.info("뉴스 사전 생성 완료: prepare_id=%s, %d개", prepare_id, len(market._news_queue))

        asyncio.create_task(_do_prepare())
        return {"prepare_id": prepare_id}

    @app.get("/api/stocks/prepare/{prepare_id}")
    async def prepare_status(prepare_id: str):
        news = _prepared_news.get(prepare_id)
        ready = isinstance(news, list) and len(news) > 0
        return {"ready": ready, "count": len(news) if ready else 0}

    # ── 엔드포인트 ──────────────────────────────────────────────────────────────

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/games")
    async def list_games():
        return [g.to_dict() for g in registry.list_games()]

    @app.post("/api/games", status_code=201)
    async def create_game(body: CreateGameRequest):
        cfg = DEFAULT_CONFIG

        user_bots: list[BotInterface] = []
        for b in body.bots:
            if len(b.code) > 50 * 1024:
                raise HTTPException(400, "코드가 너무 큽니다 (최대 50KB).")
            bot = InProcessBot(b.bot_id, b.code)
            user_bots.append(bot)

        filler_bots: list[BotInterface] = []
        if body.fill_with_ai:
            from bots.long_term import LongTermBot
            from bots.short_trader import ShortTraderBot
            filler_classes = [LongTermBot, ShortTraderBot, RandomBot]
            filler_labels  = ["장기봇", "단기봇", "AI"]
            existing_ids = {b.bot_id for b in user_bots}
            needed = max(0, body.min_bots - len(user_bots))
            for i in range(needed):
                cls_idx = i % len(filler_classes)
                bot_id  = f"{filler_labels[cls_idx]}_{i:02d}"
                while bot_id in existing_ids:
                    i += 1
                    bot_id = f"{filler_labels[cls_idx]}_{i:02d}"
                existing_ids.add(bot_id)
                filler_bots.append(filler_classes[cls_idx](bot_id=bot_id))

        # 사전 생성된 뉴스 꺼내기
        prepared_news = None
        if body.prepare_id and body.prepare_id in _prepared_news:
            prepared_news = _prepared_news.pop(body.prepare_id)

        session = registry.create_game(
            config=cfg,
            tick_interval=body.tick_interval,
            seed=body.seed,
        )
        session.register_bots(user_bots + filler_bots)

        try:
            await session.start(prepared_news=prepared_news)
        except Exception as e:
            registry.remove_game(session.game_id)
            raise HTTPException(500, str(e))

        return {"game_id": session.game_id, **session.get_info().to_dict()}

    @app.get("/api/games/{game_id}")
    async def get_game(game_id: str):
        session = registry.get_game(game_id)
        if not session:
            raise HTTPException(404, "게임을 찾을 수 없습니다.")
        return session.get_info().to_dict()

    @app.get("/api/games/{game_id}/result")
    async def get_result(game_id: str):
        session = registry.get_game(game_id)
        if not session:
            raise HTTPException(404, "게임을 찾을 수 없습니다.")
        snap = session.get_last_snapshot()
        if not snap:
            raise HTTPException(404, "결과가 아직 없습니다.")
        return snap

    @app.delete("/api/games/{game_id}", status_code=204)
    async def delete_game(game_id: str):
        session = registry.get_game(game_id)
        if not session:
            raise HTTPException(404, "게임을 찾을 수 없습니다.")
        await session.stop()
        registry.remove_game(game_id)

    @app.websocket("/ws/games/{game_id}")
    async def ws_spectate(websocket: WebSocket, game_id: str):
        session = registry.get_game(game_id)
        if not session:
            await websocket.close(code=4004)
            return

        await spectator_manager.connect(game_id, websocket)
        if session.get_last_snapshot():
            await websocket.send_json({
                "type": "tick",
                "game_id": game_id,
                "data": session.get_last_snapshot(),
            })

        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            spectator_manager.disconnect(game_id, websocket)

    return app
