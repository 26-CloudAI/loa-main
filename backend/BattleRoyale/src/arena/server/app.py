"""
AI Arena — FastAPI 서버

엔드포인트:
  POST   /api/games              게임 생성 + 봇 등록 + 시작
  GET    /api/games              활성 게임 목록
  GET    /api/games/{id}         게임 정보
  GET    /api/games/{id}/result  게임 결과
  DELETE /api/games/{id}         게임 강제 종료
  WS     /ws/games/{id}          실시간 관전 WebSocket

의존성: fastapi, uvicorn, redis (선택)
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

# FastAPI import를 안전하게 처리
try:
    from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

# 프로젝트 경로
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from ..bot_interface import BotInterface
from ..config import DEFAULT_CONFIG
from . import settings as _settings
from .config import DEFAULT_SERVER_CONFIG, ServerConfig
from .game_session import GameRegistry, GameSession
from fastapi import Depends
from ..auth.firebase_handler import verify_firebase_token
from ..db import init_db, UserRepository, BotRepository
from ..auth.auth_service import FirebaseUserService

from .redis_manager import (
    InMemoryPubSubBroker,
    InMemoryStateStore,
    create_pubsub_broker,
    create_state_store,
)
from .schemas import (
    GameStatus,
    make_error_message,
)
from .ws_manager import SpectatorManager
from ..mock_auth.router import router as mock_auth_router

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#  콜드스타트 봇 팩토리 (인프로세스용)
# ──────────────────────────────────────────────

class InProcessBot(BotInterface):
    """
    유저 코드를 같은 프로세스에서 실행하는 어댑터.
    Phase 1 로컬 테스트 및 Docker 없는 개발 환경에서 사용.
    """

    def __init__(self, bot_id: str, code: str):
        self._bot_id = bot_id
        self._action_fn = None
        self._load_error: Optional[str] = None

        try:
            local_ns: dict = {"__builtins__": __builtins__}
            exec(code, local_ns)
            fn = local_ns.get("action")
            if fn is None or not callable(fn):
                raise ValueError("action(state) 함수를 찾을 수 없습니다.")
            self._action_fn = fn
        except Exception as e:
            self._load_error = str(e)
            logger.warning("봇 %s 코드 로드 실패: %s", bot_id, e)

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def get_action(self, state: dict) -> str:
        if self._action_fn is None:
            return "STAY"
        try:
            result = self._action_fn(state)
            return str(result) if result else "STAY"
        except Exception:
            return "STAY"


def _create_filler_bots(count: int, existing_ids: set[str]) -> list[BotInterface]:
    """빈 슬롯을 채우는 AI 봇 생성."""
    from bots.herbivore import HerbivoreBot
    from bots.mad_dog import MadDogBot
    from bots.camper import CamperBot

    bot_classes = [HerbivoreBot, MadDogBot, CamperBot]
    labels = ["AI_초식", "AI_미친개", "AI_존버"]
    fillers = []

    for i in range(count):
        cls_idx = i % len(bot_classes)
        bot_id = f"{labels[cls_idx]}_{i:02d}"
        while bot_id in existing_ids:
            i += count
            bot_id = f"{labels[cls_idx]}_{i:02d}"
        existing_ids.add(bot_id)
        fillers.append(bot_classes[cls_idx](bot_id=bot_id, seed=i))

    return fillers


def _create_boss_bot(existing_ids: set[str]) -> BotInterface:
    """보스전용 RLBossBot 1개 생성."""
    from bots.rl_boss_bot import RLBossBot
    bot_id = "AI_보스"
    existing_ids.add(bot_id)
    return RLBossBot(bot_id=bot_id, seed=0)

# ──────────────────────────────────────────────
#  Pydantic 스키마 (데이터 검증용) -> 클라이언트가 보낸 JSON울 파이썬 객체로 변환
# ──────────────────────────────────────────────
class BotCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="봇 이름")
    code: str = Field(..., description="봇 파이썬 코드")

class BotUpdateRequest(BaseModel):
    code: str = Field(..., description="업데이트할 봇 파이썬 코드")

# ──────────────────────────────────────────────
#  FastAPI 앱 생성
# ──────────────────────────────────────────────

def create_app(
    server_config: ServerConfig = DEFAULT_SERVER_CONFIG,
    use_redis: bool = False,
) -> "FastAPI":
    """FastAPI 앱 인스턴스를 생성한다."""
    if not FASTAPI_AVAILABLE:
        raise RuntimeError(
            "fastapi 패키지가 필요합니다. "
            "'pip install fastapi uvicorn' 실행하세요."
        )

    # 공유 상태
    state = {"registry": None, "spectator_mgr": None}

    # 레이트리밋: IP별 요청 타임스탬프 (슬라이딩 윈도우)
    _rate_limit_store: dict[str, deque] = defaultdict(deque)
    _RATE_LIMIT_MAX = 3       # 최대 요청 수
    _RATE_LIMIT_WINDOW = 60   # 슬라이딩 윈도우 (초)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 시작
        store = await create_state_store(server_config.redis, use_redis)
        pubsub = await create_pubsub_broker(server_config.redis, use_redis)

        registry = GameRegistry(store, pubsub, server_config)
        spectator_mgr = SpectatorManager(server_config.websocket, pubsub)

        state["registry"] = registry
        state["spectator_mgr"] = spectator_mgr

        db_conn = init_db()
        user_repo = UserRepository(db_conn)
        bot_repo = BotRepository(db_conn)
        firebase_user_svc = FirebaseUserService(user_repo)
        state["db_conn"] = db_conn
        state["bot_repo"] = bot_repo
        state["firebase_user_svc"] = firebase_user_svc

        logger.info(
            "서버 시작 (Redis: %s)", "활성" if use_redis else "인메모리"
        )

        # 백그라운드 정리 태스크 (5분 주기)
        async def _cleanup_loop():
            while True:
                await asyncio.sleep(300)
                removed = await registry.cleanup_finished()
                if removed:
                    logger.info("종료된 게임 정리: %d개 삭제됨", removed)

        cleanup_task = asyncio.create_task(_cleanup_loop())

        yield
        
        db_conn.close()

        # 종료
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        await spectator_mgr.cleanup()
        logger.info("서버 종료")

    app = FastAPI(
        title="AI Arena",
        description="AI 봇 배틀로얄 실시간 관전 플랫폼",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if _settings.ENV != "production":
        app.include_router(mock_auth_router)

        from ..auth.auth_service import decode_token, TokenConfig
        from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

        _dev_bearer = HTTPBearer(auto_error=False)

        async def _dev_verify_token(
            credentials: Optional[HTTPAuthorizationCredentials] = Depends(_dev_bearer),
        ) -> dict:
            if not credentials:
                raise HTTPException(401, "인증 토큰이 없습니다.")
            config = TokenConfig(secret_key=_settings.JWT_SECRET)
            payload = decode_token(credentials.credentials, config)
            if not payload:
                raise HTTPException(401, "유효하지 않거나 만료된 토큰입니다.")
            return {"uid": payload.get("sub"), "email": payload.get("email", "")}

        app.dependency_overrides[verify_firebase_token] = _dev_verify_token

    def _registry() -> GameRegistry:
        return state["registry"]

    def _spectator_mgr() -> SpectatorManager:
        return state["spectator_mgr"]

    def _bot_repo() -> BotRepository:
        return state["bot_repo"]

    def _firebase_user_svc() -> FirebaseUserService:
        return state["firebase_user_svc"]

    # ── REST API ──

    @app.post("/api/games")
    async def create_game(request: Request, body: dict):
        """
        게임을 생성하고 시작한다.

        Body:
        {
            "bots": [{"bot_id": "my_bot", "code": "def action(state): ..."}],
            "tick_interval": 0.05,
            "seed": 42,
            "fill_with_ai": true,
            "min_bots": 4
        }
        """
        # 레이트리밋: IP당 60초 슬라이딩 윈도우 내 최대 3회
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        timestamps = _rate_limit_store[client_ip]
        # 윈도우 밖의 오래된 타임스탬프 제거
        while timestamps and now - timestamps[0] > _RATE_LIMIT_WINDOW:
            timestamps.popleft()
        if len(timestamps) >= _RATE_LIMIT_MAX:
            raise HTTPException(
                status_code=429,
                detail=f"요청 한도 초과: {_RATE_LIMIT_WINDOW}초당 최대 {_RATE_LIMIT_MAX}회",
            )
        timestamps.append(now)

        registry = _registry()
        bots_data = body.get("bots", [])
        tick_interval = body.get("tick_interval", 0.05)
        seed = body.get("seed")
        fill_with_ai = body.get("fill_with_ai", True)
        min_bots = body.get("min_bots", 4)
        mode = body.get("mode", "battle-royale")

        # 봇 코드 크기 검증
        max_size = server_config.api.max_bot_code_size
        for b in bots_data:
            if len(b.get("code", "")) > max_size:
                raise HTTPException(
                    400,
                    f"봇 {b.get('bot_id', '?')} 코드가 {max_size}B를 초과합니다.",
                )

        # 게임 세션 생성
        session = registry.create_game(
            tick_interval=tick_interval,
            seed=seed,
        )

        # 유저 봇 등록
        bot_interfaces: list[BotInterface] = []
        existing_ids: set[str] = set()

        for b in bots_data:
            bot = InProcessBot(b["bot_id"], b["code"])
            bot_interfaces.append(bot)
            existing_ids.add(b["bot_id"])

        if mode == "boss":
            # 보스전: 유저 봇 1명 + RLBossBot 1명
            if len(bot_interfaces) != 1:
                raise HTTPException(400, "보스전은 봇 1개만 등록할 수 있습니다.")
            bot_interfaces.append(_create_boss_bot(existing_ids))
        elif fill_with_ai and len(bot_interfaces) < min_bots:
            # 배틀로얄: AI 봇으로 빈 슬롯 채우기
            filler_count = min_bots - len(bot_interfaces)
            fillers = _create_filler_bots(filler_count, existing_ids)
            bot_interfaces.extend(fillers)

        if len(bot_interfaces) < 2:
            raise HTTPException(400, "최소 2개의 봇이 필요합니다.")

        session.register_bots(bot_interfaces)
        await session.start()

        return session.get_info().to_dict()

    @app.get("/api/games")
    async def list_games():
        """활성 게임 목록."""
        return [g.to_dict() for g in _registry().list_games()]

    @app.get("/api/games/{game_id}")
    async def get_game(game_id: str):
        """게임 정보."""
        session = _registry().get_game(game_id)
        if not session:
            raise HTTPException(404, "게임을 찾을 수 없습니다.")
        return session.get_info().to_dict()

    @app.get("/api/games/{game_id}/result")
    async def get_game_result(game_id: str):
        """게임 결과."""
        registry = _registry()
        session = registry.get_game(game_id)

        if session and session.status != GameStatus.FINISHED:
            raise HTTPException(400, "게임이 아직 진행 중입니다.")

        result = await registry.state_store.get_game_result(game_id)
        if not result:
            raise HTTPException(404, "게임 결과를 찾을 수 없습니다.")
        return result

    @app.delete("/api/games/{game_id}")
    async def stop_game(game_id: str):
        """게임을 강제 종료."""
        session = _registry().get_game(game_id)
        if not session:
            raise HTTPException(404, "게임을 찾을 수 없습니다.")
        await session.stop()
        return {"status": "stopped", "game_id": game_id}

    # ── WebSocket ──

    @app.websocket("/ws/games/{game_id}")
    async def spectate_game(websocket: WebSocket, game_id: str):
        """게임 실시간 관전 WebSocket."""
        registry = _registry()
        mgr = _spectator_mgr()

        session = registry.get_game(game_id)
        if not session:
            await websocket.close(code=4004, reason="게임을 찾을 수 없습니다.")
            return

        await websocket.accept()

        try:
            conn = await mgr.add_spectator(game_id, websocket)
        except ConnectionRefusedError as e:
            await websocket.send_json(make_error_message(str(e)))
            await websocket.close(code=4003)
            return

        try:
            # 현재 상태 즉시 전송 (중간 참여 지원)
            current = await registry.state_store.get_game_state(game_id)
            if current:
                await websocket.send_json({
                    "type": "tick",
                    "data": current,
                })

            # 클라이언트 메시지 수신 대기 (ping/pong, 연결 유지)
            while True:
                try:
                    data = await websocket.receive_text()
                    # 현재는 클라이언트→서버 메시지 무시
                except WebSocketDisconnect:
                    break
        finally:
            await mgr.remove_spectator(game_id, conn)

    # ── 헬스체크 ──

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "active_games": len(_registry().list_games()),
            "total_spectators": _spectator_mgr().get_total_connections(),
        }
        
    # ── 봇 CRUD API ──

    @app.post("/api/bots", status_code=201)
    async def register_bot(body: BotCreateRequest, user: dict = Depends(verify_firebase_token)):
        repo = _bot_repo()
        ok, err = repo.validate_code(body.code)
        if not ok:
            raise HTTPException(400, err)
        db_user = _firebase_user_svc().get_or_create_user(user)
        bot = repo.create(user_id=db_user.id, name=body.name, code=body.code)
        return {"message": "봇이 성공적으로 등록되었습니다.", "bot": {"id": bot.id, "name": bot.name, "version": bot.version}}

    @app.get("/api/bots")
    async def list_my_bots(user: dict = Depends(verify_firebase_token)):
        db_user = _firebase_user_svc().get_or_create_user(user)
        bots = _bot_repo().get_by_user(db_user.id)
        return {"bots": [{"id": b.id, "name": b.name, "version": b.version, "win_rate": b.win_rate} for b in bots]}

    @app.get("/api/bots/{bot_id}")
    async def get_bot(bot_id: int, user: dict = Depends(verify_firebase_token)):
        bot = _bot_repo().get_by_id(bot_id)
        if not bot or not bot.is_active:
            raise HTTPException(404, "봇을 찾을 수 없습니다.")
        db_user = _firebase_user_svc().get_or_create_user(user)
        if bot.user_id != db_user.id:
            raise HTTPException(403, "접근 권한이 없습니다.")
        return {"id": bot.id, "name": bot.name, "code": bot.code, "version": bot.version}

    @app.put("/api/bots/{bot_id}")
    async def update_bot(bot_id: int, body: BotUpdateRequest, user: dict = Depends(verify_firebase_token)):
        repo = _bot_repo()
        bot = repo.get_by_id(bot_id)
        if not bot or not bot.is_active:
            raise HTTPException(404, "봇을 찾을 수 없습니다.")
        db_user = _firebase_user_svc().get_or_create_user(user)
        if bot.user_id != db_user.id:
            raise HTTPException(403, "접근 권한이 없습니다.")
        ok, err = repo.validate_code(body.code)
        if not ok:
            raise HTTPException(400, err)
        updated = repo.update_code(bot_id, body.code)
        return {"message": "봇이 성공적으로 업데이트되었습니다.", "bot": {"id": updated.id, "version": updated.version}}

    @app.delete("/api/bots/{bot_id}")
    async def delete_bot(bot_id: int, user: dict = Depends(verify_firebase_token)):
        repo = _bot_repo()
        bot = repo.get_by_id(bot_id)
        if not bot or not bot.is_active:
            raise HTTPException(404, "봇을 찾을 수 없습니다.")
        db_user = _firebase_user_svc().get_or_create_user(user)
        if bot.user_id != db_user.id:
            raise HTTPException(403, "접근 권한이 없습니다.")
        repo.soft_delete(bot_id)
        return {"message": "봇이 삭제되었습니다."}

    return app
