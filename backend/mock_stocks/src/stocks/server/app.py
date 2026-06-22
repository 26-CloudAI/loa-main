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
import json as _json
import logging
import os as _os
import sys
import urllib.request as _urllib
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..bot_interface import BotInterface
from ..config import Config, DEFAULT_CONFIG
from ..db.schema import init_db
from ..db.game_repo import StockGameRepository
from ..market import Market
from . import settings as _settings
from .game_session import GameRegistry
from .ws_manager import SpectatorManager

# ── Gemini API 키 (코드 생성용) ────────────────────────────────────────────
try:
    from gemini_key import GEMINI_API_KEY as _GEMINI_KEY  # type: ignore[import]
    if _GEMINI_KEY == "여기에_Gemini_API_키_입력":
        _GEMINI_KEY = None
except ImportError:
    _GEMINI_KEY = _os.getenv("GEMINI_API_KEY") or None


def _call_gemini_generate(prompt: str, timeout: int = 30) -> str | None:
    if not _GEMINI_KEY:
        return None
    try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta"
            f"/models/gemini-2.5-flash:generateContent?key={_GEMINI_KEY}"
        )
        body = _json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
        }).encode("utf-8")
        req = _urllib.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _urllib.urlopen(req, timeout=timeout) as resp:
            result = _json.loads(resp.read().decode("utf-8"))
        return result["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        logger.warning("Gemini API 호출 실패: %s", e)
        return None


def _extract_code(text: str) -> str:
    if "```" in text:
        for part in text.split("```"):
            part = part.strip().lstrip("python").strip()
            if part.startswith(("import ", "from ", "class ", "def ", "#")):
                return part
    return text.strip()


_STOCKS_SYSTEM_PROMPT = """\
You are a Python trading bot code generator for a MockStocks game.
Output ONLY valid Python code with NO explanations, NO markdown.

RULES:
- Must define: def action(state: dict) -> dict
- Allowed imports ONLY: math, random, json, collections

STATE:
  state["tick"]: int                       # current turn 1-200
  state["my_bot"]["cash"]: float
  state["my_bot"]["total_value"]: float
  state["my_bot"]["portfolio"]: dict       # {symbol: quantity_held}
  state["my_bot"]["short_positions"]: dict # {symbol: quantity_shorted}
  state["my_bot"]["credit_score"]: int     # 0-1000; SHORT requires >= 800
  state["market"]["stocks"]: list of {symbol, price, price_history:[floats], volume}
  state["market"]["news"]: list of str     # recent news strings

RETURN one of:
  {"action": "HOLD"}
  {"action": "BUY",   "symbol": "X", "quantity": N}
  {"action": "SELL",  "symbol": "X", "quantity": N}
  {"action": "SHORT", "symbol": "X", "quantity": N}    # credit_score >= 800
  {"action": "COVER", "symbol": "X", "quantity": N}
  {"action": "INQUIRY"}                                # get next news hint (0.01%/turn interest on HOLD)

Initial capital: 100,000,000 KRW. Win: highest total_value after 200 turns.
Available stocks: NeoChips, BioFusion, QuantumDrive, SolarEdge, CyberMed,
DataVault, AeroNext, GreenCore, RoboTech, SpaceMine, NanoMed, HyperGrid,
OceanFarm, CryptoBase, MindLink.
"""


class BotSubmission(BaseModel):
    bot_id: str
    code: str

class CreateGameRequest(BaseModel):
    bots: list[BotSubmission] = []
    fill_with_ai: bool = True
    min_bots: int = 4
    tick_interval: float = 0.1
    seed: Optional[int] = None
    name: Optional[str] = None
    prepare_id: Optional[str] = None  # 사전 생성된 뉴스 ID

logger = logging.getLogger(__name__)


def _get_uid(request: Request) -> Optional[str]:
    """Authorization 헤더에서 Firebase UID를 추출한다. 실패 시 None 반환."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[len("Bearer "):]
    try:
        import firebase_admin.auth as fb_auth
        decoded = fb_auth.verify_id_token(token)
        return decoded.get("uid")
    except Exception:
        return None


def _require_uid(request: Request) -> str:
    """UID를 반환하거나, 인증 실패 시 401을 발생시킨다."""
    uid = _get_uid(request)
    if uid is None:
        raise HTTPException(401, "인증이 필요합니다.")
    return uid


# ── InProcessBot ──────────────────────────────────────────────────────────────

_FORBIDDEN_BUILTINS = frozenset({
    "open", "exec", "eval", "compile", "__import__",
    "input", "breakpoint", "memoryview",
    "globals", "vars",
})

_ALLOWED_MODULES = frozenset({"math", "random", "json", "collections", "heapq", "itertools"})


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    root = name.split(".")[0]
    if root not in _ALLOWED_MODULES:
        raise ImportError("허용되지 않은 모듈 import: %s" % name)
    return __import__(name, globals, locals, fromlist, level)


def _restricted_builtins() -> dict:
    import builtins as _b
    safe = {}
    for name in dir(_b):
        if name.startswith("_"):
            continue
        if name in _FORBIDDEN_BUILTINS:
            continue
        safe[name] = getattr(_b, name)
    safe["__import__"] = _safe_import
    safe["__build_class__"] = _b.__build_class__
    return safe


_RESTRICTED_BUILTINS = _restricted_builtins()


class InProcessBot(BotInterface):
    """유저 제출 코드를 실행하는 어댑터."""

    def __init__(self, bot_id: str, code: str):
        super().__init__(bot_id)
        self.code = code
        self._action_fn = None
        self._load_error: Optional[str] = None
        try:
            ns: dict = {"__builtins__": _RESTRICTED_BUILTINS}
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
    spectator_manager = SpectatorManager()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 재시도로 늦게 생긴 conn도 shutdown에서 닫을 수 있도록 holder로 보관.
        conn_holder = {"conn": None}

        def _init_repository():
            # 연결 + repo 생성만 한다(여러 번/늦게 실행돼도 안전, 멱등). 미완료 게임 정리
            # (destructive)는 여기서 하지 않는다 — 승자 연결로 단 1회, 트래픽 유입 전에만.
            db_conn = None
            try:
                db_conn = init_db()
                repo = StockGameRepository(db_conn)
                return db_conn, repo
            except Exception:
                if db_conn is not None:
                    db_conn.close()
                raise

        loop = asyncio.get_running_loop()
        winner_chosen = False  # 첫 성공 결과 채택 여부 (정리/설치 single-flight)
        finalize_task = None

        def _accept_winner(result) -> None:
            """첫 성공 결과만 승자로 채택한다. 승자 연결로 미완료 게임 정리(1회)를
            마친 뒤 registry._repo를 설치한다(트래픽 유입 전). 패자(늦게 끝난 시도 포함)는
            연결만 닫고 destructive 정리를 절대 재실행하지 않는다 → 라이브 게임 보호."""
            nonlocal winner_chosen, finalize_task
            db_conn, repo = result
            if winner_chosen:
                try:
                    db_conn.close()
                except Exception:
                    logger.exception("중복 DB 연결 닫기 실패")
                return
            winner_chosen = True

            async def _finalize():
                # 미완료 게임 정리는 registry._repo 설치(=게임 생성 가능) 전에 끝내 정리가
                # 라이브 게임을 건드리지 못하게 한다. 정리 실패해도 연결은 쓸 수 있으므로
                # readiness는 활성화.
                try:
                    stale = await loop.run_in_executor(None, repo.cleanup_stale_games)
                except Exception:
                    logger.exception("미완료 게임 정리 실패 — 무시하고 readiness 활성화")
                    stale = 0
                conn_holder["conn"] = db_conn
                registry._repo = repo
                if stale:
                    logger.info("MockStocks 재시작: %d개 미완료 게임을 error 상태로 변경", stale)

            finalize_task = loop.create_task(_finalize())

        async def _init_once() -> None:
            """init 시도 1건: executor에서 연결+repo 생성 후 승자 채택을 시도."""
            try:
                result = await loop.run_in_executor(None, _init_repository)
            except Exception as e:
                logger.exception("MockStocks DB 초기화 실패, DB 없이 기동: %s", e)
                return
            _accept_winner(result)

        # startup DB init이 실패해도 프로세스는 산다(liveness 유지, 기존 비차단 설계). 단
        # readiness가 영구 503으로 latch되지 않도록 DB가 살아나면 백그라운드 재시도로
        # registry._repo를 다시 채워 db_ok() 람다가 자동으로 truthy로 flip되게 한다.
        #
        # 첫 시도는 startup을 막지 않도록 DB_INIT_TIMEOUT_SEC 안에서만 기다린다. 타임아웃돼도
        # executor 스레드는 멈출 수 없으므로 shield로 살려두고, 늦은 결과는 _accept_winner가
        # 흡수한다(승자면 설치, 아니면 연결만 닫음 → 늦은 정리로 인한 라이브 게임 손상 방지).
        # 재시도는 await로 직렬 실행되어 시도가 중첩 누적되지 않는다.
        startup_init = asyncio.create_task(_init_once())
        try:
            await asyncio.wait_for(asyncio.shield(startup_init), timeout=_settings.DB_INIT_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            logger.warning(
                "MockStocks DB 초기화가 %.0fs 내 미완료 — 백그라운드에서 계속 시도",
                _settings.DB_INIT_TIMEOUT_SEC,
            )
        except Exception:
            pass  # 실패는 _init_once가 이미 로깅

        db_retry_task = None
        if not winner_chosen:
            async def _db_retry_loop():
                while not winner_chosen:
                    await asyncio.sleep(_settings.DB_RETRY_INTERVAL_SEC)
                    if not winner_chosen:
                        await _init_once()
                logger.info("MockStocks DB 연결 복구됨 — readiness 회복")
            db_retry_task = asyncio.create_task(_db_retry_loop())

        # 서버 시작 시 뉴스 풀 미리 채우기 시작
        asyncio.create_task(_fill_pool())
        logger.info("뉴스 풀 사전 생성 시작")

        yield

        for _t in (db_retry_task, finalize_task, startup_init):
            if _t is not None:
                _t.cancel()
                try:
                    await _t
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

        if conn_holder["conn"] is not None:
            conn_holder["conn"].close()

    app = FastAPI(title="MockStocks API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request, exc):
        logger.exception("Unhandled exception in MockStocks: %s %s", request.method, request.url)
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

    registry = GameRegistry(spectator_manager)

    # Bot Runner readiness 용 DB 상태 노출 (run_server.py /healthz 에서 사용)
    app.state.db_ok = lambda: registry._repo is not None

    # ── 뉴스 풀 ───────────────────────────────────────────────────────────────
    # 서버가 미리 만들어두는 뉴스 배치. 유저가 /prepare 호출 시 즉시 꺼내줌.
    NEWS_POOL_TARGET = 2                 # 항상 유지할 배치 수
    _news_pool: list[dict] = []          # {"queue": [...], "source": str}
    _pool_filling: bool = False          # 현재 채우는 중 여부 (중복 방지)

    async def _fill_pool() -> None:
        """풀이 목표치(2개) 미달이면 백그라운드에서 순차적으로 채운다."""
        nonlocal _pool_filling
        if _pool_filling:
            return  # 이미 채우는 중이면 스킵
        if len(_news_pool) >= NEWS_POOL_TARGET:
            return  # 이미 충분함

        _pool_filling = True
        try:
            market = Market(DEFAULT_CONFIG)
            source = await asyncio.get_event_loop().run_in_executor(
                None, market.pregenerate_news_batch, 20
            )
            _news_pool.append({"queue": market._news_queue, "source": source})
            logger.info(
                "뉴스 풀 채움: %d/%d (source=%s)",
                len(_news_pool), NEWS_POOL_TARGET, source,
            )
        except Exception:
            logger.exception("뉴스 풀 채우기 실패")
        finally:
            _pool_filling = False

        # 아직 목표치 미달이면 한 번 더 채우기
        if len(_news_pool) < NEWS_POOL_TARGET:
            asyncio.create_task(_fill_pool())

    # prepare_id → {"queue": list, "source": str} | None(생성 중)
    _prepared_news: dict[str, dict | None] = {}

    # ── 뉴스 사전 생성 ──────────────────────────────────────────────────────────

    @app.post("/api/stocks/prepare")
    async def prepare_news():
        prepare_id = str(uuid.uuid4())[:8]

        if _news_pool:
            # 풀에 준비된 배치가 있으면 즉시 꺼내줌
            batch = _news_pool.pop(0)
            _prepared_news[prepare_id] = batch
            logger.info(
                "뉴스 풀에서 즉시 제공: prepare_id=%s, %d개 (source=%s)",
                prepare_id, len(batch["queue"]), batch["source"],
            )
            # 풀이 비었으니 백그라운드에서 다시 채우기 시작
            asyncio.create_task(_fill_pool())
        else:
            # 풀이 비어있으면 이 요청 전용으로 직접 생성
            _prepared_news[prepare_id] = None

            async def _do_prepare():
                market = Market(DEFAULT_CONFIG)
                source = await asyncio.get_event_loop().run_in_executor(
                    None, market.pregenerate_news_batch, 20
                )
                _prepared_news[prepare_id] = {
                    "queue": market._news_queue,
                    "source": source,
                }
                logger.info(
                    "뉴스 온디맨드 생성 완료: prepare_id=%s, %d개 (source=%s)",
                    prepare_id, len(market._news_queue), source,
                )

            asyncio.create_task(_do_prepare())

        return {"prepare_id": prepare_id}

    @app.get("/api/stocks/prepare/{prepare_id}")
    async def prepare_status(prepare_id: str):
        entry = _prepared_news.get(prepare_id)
        if entry is None:
            return {"ready": False, "count": 0, "source": "loading"}
        queue = entry.get("queue", [])
        source = entry.get("source", "template")
        return {"ready": True, "count": len(queue), "source": source}

    # ── 엔드포인트 ──────────────────────────────────────────────────────────────

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/games")
    async def list_games(request: Request):
        uid = _require_uid(request)
        return [g.to_dict() for g in registry.list_games(owner_uid=uid)]

    @app.get("/api/games/history")
    async def list_history(request: Request, limit: int = 50):
        """완료된 MockStocks 게임 기록을 DB에서 조회. lifespan 전이거나 repo 미설정 시 빈 목록 반환."""
        uid = _require_uid(request)
        repo = registry._repo
        if repo is None:
            raise HTTPException(503, "MockStocks DB를 사용할 수 없습니다.")

        games = repo.get_finished_games(limit=limit, owner_uid=uid)
        result = []
        for g in games:
            participants = repo.get_participants(g.id)
            rankings = [
                {
                    "rank": p.final_rank,
                    "bot_id": p.bot_id,
                    "bot_name": p.bot_name,
                    "is_ai_filler": p.is_ai_filler,
                    "final_total_value": p.final_total_value,
                    "profit_rate": p.profit_rate,
                    "final_credit_score": p.final_credit_score,
                }
                for p in participants
                if p.final_rank is not None
            ]
            result.append({
                "game_id": g.id,
                "status": g.status,
                "mode": "mock-stocks",
                "current_tick": g.final_tick or 0,
                "total_bots": g.total_bots,
                "alive_bots": 0,
                "bot_ids": [p.bot_id for p in participants],
                "name": g.name,
                "created_at": g.created_at,
                "finished_at": g.finished_at,
                "end_reason": g.end_reason,
                "rankings": rankings,
            })
        return result

    @app.post("/api/games", status_code=201)
    async def create_game(body: CreateGameRequest, request: Request):
        uid = _require_uid(request)
        cfg = DEFAULT_CONFIG

        user_bots: list[BotInterface] = []
        for b in body.bots:
            if len(b.code) > 50 * 1024:
                raise HTTPException(400, "코드가 너무 큽니다 (최대 50KB).")
            if _settings.BOT_RUNNER_URL:
                from ..sandbox.remote_adapter import RemoteStockBotAdapter
                bot = RemoteStockBotAdapter(
                    bot_id=b.bot_id,
                    code=b.code,
                    runner_url=_settings.BOT_RUNNER_URL,
                    timeout=_settings.BOT_RUNNER_TIMEOUT_SEC,
                )
            elif _settings.ENV == "production" and _settings.BOT_RUNNER_REQUIRED:
                raise HTTPException(503, "Bot Runner is required but BOT_RUNNER_URL is not configured")
            else:
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
                filler_bots.append(filler_classes[cls_idx](bot_id=bot_id, is_ai_filler=True))

        # 사전 생성된 뉴스 꺼내기
        prepared_news = None
        if body.prepare_id and body.prepare_id in _prepared_news:
            entry = _prepared_news.pop(body.prepare_id)
            if entry is not None:
                prepared_news = entry.get("queue") or None

        if registry._repo is None:
            raise HTTPException(503, "MockStocks DB를 사용할 수 없습니다.")
        name = body.name.strip() if body.name else None
        next_index = registry._repo.count_games_by_owner(uid) + 1
        session = registry.create_game(
            config=cfg,
            tick_interval=body.tick_interval,
            seed=body.seed,
            owner_uid=uid,
        )
        if not name:
            name = f"새 모의주식 {next_index}"
        session.name = name
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
        if session:
            engine = session._engine
            result = engine.game_result if engine else None
            if result:
                initial_cash = session._cfg.game.starting_cash
                return {
                    "game_id": game_id,
                    "name": session.name,
                    "status": "finished",
                    "final_tick": result.final_tick,
                    "end_reason": "finished",
                    "finished_at": None,
                    "rankings": [
                        {
                            "rank": entry["rank"],
                            "bot_id": entry["id"],
                            "bot_name": entry["id"],
                            "is_ai_filler": False,
                            "final_total_value": entry["total_value"],
                            "profit_rate": (entry["total_value"] - initial_cash) / initial_cash * 100,
                        }
                        for entry in result.rankings
                    ],
                }

        # 인메모리에 없으면 DB 폴백 (서버 재시작 후 종료 게임 조회)
        repo = registry._repo
        if repo is None:
            raise HTTPException(404, "결과가 없습니다.")
        game = repo.get_game(game_id)
        if not game or game.status != "finished":
            raise HTTPException(404, "완료된 게임을 찾을 수 없습니다.")
        participants = repo.get_participants(game_id)
        return {
            "game_id": game_id,
            "name": game.name,
            "status": "finished",
            "final_tick": game.final_tick,
            "end_reason": game.end_reason,
            "finished_at": game.finished_at,
            "rankings": [
                {
                    "rank": p.final_rank,
                    "bot_id": p.bot_id,
                    "bot_name": p.bot_name,
                    "is_ai_filler": p.is_ai_filler,
                    "final_total_value": p.final_total_value,
                    "profit_rate": p.profit_rate,
                }
                for p in participants
                if p.final_rank is not None
            ],
        }

    @app.get("/api/games/{game_id}/replay")
    async def get_game_replay(game_id: str, request: Request):
        """게임 리플레이 전체 스냅샷을 반환."""
        session = registry.get_game(game_id)
        if not session:
            raise HTTPException(404, "리플레이 데이터가 없습니다.")
        frames = session.get_replay_frames()
        if not frames:
            raise HTTPException(404, "리플레이 프레임이 아직 없습니다.")
        engine = session._engine
        result_data = None
        if engine and engine.game_result:
            initial_cash = session._cfg.game.starting_cash
            result_data = {
                "final_tick": engine.game_result.final_tick,
                "rankings": [
                    {
                        "rank": e["rank"],
                        "bot_id": e["id"],
                        "final_total_value": e["total_value"],
                        "profit_rate": (e["total_value"] - initial_cash) / initial_cash * 100,
                        "credit_score": e.get("credit_score", 0),
                    }
                    for e in engine.game_result.rankings
                ],
            }
        return {
            "game_id": game_id,
            "total_frames": len(frames),
            "frames": frames,
            "result": result_data,
        }

    @app.get("/api/users/me/bots")
    async def get_my_bots(request: Request):
        """인증된 유저의 모의주식 봇 제출 이력을 반환한다."""
        uid = _require_uid(request)
        repo = registry._repo
        if repo is None:
            return []
        return repo.get_user_bots(uid)

    @app.get("/api/users/me/stats")
    async def get_my_stats(request: Request):
        """인증된 유저의 모의주식 전적을 반환한다."""
        uid = _require_uid(request)
        repo = registry._repo
        if repo is None:
            return {"games_played": 0, "wins": 0, "losses": 0}
        return repo.get_user_stats(uid)

    @app.post("/api/bots/generate")
    async def generate_bot_code(request: Request):
        """자연어 프롬프트로 모의주식 봇 코드 생성 (Gemini 2.5 Flash)."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        user_prompt = str(body.get("prompt", "")).strip()
        if not user_prompt:
            raise HTTPException(400, "prompt가 필요합니다.")
        if not _GEMINI_KEY:
            raise HTTPException(503, "AI 코드 생성을 사용할 수 없습니다. (GEMINI_API_KEY 미설정)")
        full_prompt = f"{_STOCKS_SYSTEM_PROMPT}\n\nUser request: {user_prompt}"
        raw = _call_gemini_generate(full_prompt, timeout=30)
        if raw is None:
            raise HTTPException(502, "AI 응답을 받지 못했습니다. 잠시 후 다시 시도해주세요.")
        return {"code": _extract_code(raw), "source": "gemini"}

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
