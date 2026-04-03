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

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
import uuid

# FastAPI import를 안전하게 처리
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

# 프로젝트 경로
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from ..bot_interface import BotInterface
from ..config import DEFAULT_CONFIG
from .config import DEFAULT_SERVER_CONFIG, ServerConfig
from .game_session import GameRegistry, GameSession
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
            local_ns: dict = {}
            exec(code, {"__builtins__": __builtins__}, local_ns)
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

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 시작
        store = await create_state_store(server_config.redis, use_redis)
        pubsub = await create_pubsub_broker(server_config.redis, use_redis)

        registry = GameRegistry(store, pubsub, server_config)
        spectator_mgr = SpectatorManager(server_config.websocket, pubsub)

        state["registry"] = registry
        state["spectator_mgr"] = spectator_mgr

        logger.info(
            "서버 시작 (Redis: %s)", "활성" if use_redis else "인메모리"
        )
        yield

        # 종료
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
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mock Auth 라우터 등록 (/auth/*)
    # Firebase Auth 전환 시 이 줄만 실제 auth 라우터로 교체한다.
    app.include_router(mock_auth_router)

    def _registry() -> GameRegistry:
        return state["registry"]

    def _spectator_mgr() -> SpectatorManager:
        return state["spectator_mgr"]

    # ── REST API ──

    @app.post("/api/games")
    async def create_game(body: dict):
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
        registry = _registry()
        bots_data = body.get("bots", [])
        tick_interval = body.get("tick_interval", 0.05)
        seed = body.get("seed")
        fill_with_ai = body.get("fill_with_ai", True)
        min_bots = body.get("min_bots", 4)

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

        # AI 봇으로 빈 슬롯 채우기
        if fill_with_ai and len(bot_interfaces) < min_bots:
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

    # --- 가상의 의존성 (실제 구현 시 교체 필요) ---
    async def get_current_user():
        """현재 로그인한 사용자 정보를 가져오는 가상의 의존성"""
        return {"user_id": "mock_user_123"}
        
    # 가상의 DB 객체 (실제로는 db/bot_repo.py의 객체를 사용)
    # bot_repo = BotRepo() 
    mock_db = {} # 테스트를 위한 임시 메모리 DB

    def validate_bot_code(code: str, max_size: int):
        """봇 코드의 크기와 action(state) 함수 존재 여부를 검증합니다."""
        if len(code) > max_size:
            raise HTTPException(400, f"코드가 최대 크기({max_size}B)를 초과했습니다.")
        
        try:
            local_ns: dict = {}
            # 제한된 환경에서 코드를 실행하여 문법 오류 및 함수 존재 파악
            exec(code, {"__builtins__": __builtins__}, local_ns)
            fn = local_ns.get("action")
            if fn is None or not callable(fn):
                raise ValueError("action(state) 함수를 찾을 수 없습니다.")
        except Exception as e:
            raise HTTPException(400, f"유효하지 않은 봇 코드입니다: {str(e)}")

    # ── 봇 CRUD API ──

    @app.post("/api/bots", status_code=201)
    async def register_bot(body: BotCreateRequest): # 실제 환경: user = Depends(get_current_user)
        """새로운 봇 코드를 등록합니다."""
        user_id = "mock_user_123" # user["user_id"]
        
        # 1. 코드 검증 (크기 및 action 함수 유무)
        validate_bot_code(body.code, server_config.api.max_bot_code_size)
        
        # 2. DB 저장 로직 (bot_repo 활용)
        bot_id = str(uuid.uuid4())
        new_bot = {
            "bot_id": bot_id,
            "owner_id": user_id,
            "name": body.name,
            "code": body.code,
            "version": 1
        }
        mock_db[bot_id] = new_bot # 실제: bot_repo.create(new_bot)
        
        return {"message": "봇이 성공적으로 등록되었습니다.", "bot": new_bot}

    @app.get("/api/bots")
    async def list_my_bots(): # 실제 환경: user = Depends(get_current_user)
        """내 봇 목록을 조회합니다."""
        user_id = "mock_user_123" # user["user_id"]
        
        # 실제: bots = bot_repo.get_by_owner(user_id)
        my_bots = [b for b in mock_db.values() if b["owner_id"] == user_id]
        return {"bots": my_bots}

    @app.get("/api/bots/{bot_id}")
    async def get_bot(bot_id: str): # 실제 환경: user = Depends(get_current_user)
        """특정 봇의 상세 정보를 조회합니다."""
        # 실제: bot = bot_repo.get(bot_id)
        bot = mock_db.get(bot_id)
        if not bot:
            raise HTTPException(404, "봇을 찾을 수 없습니다.")
            
        # 권한 체크 로직 추가 가능 (내 봇만 볼 수 있게 하려면)
        return bot

    @app.put("/api/bots/{bot_id}")
    async def update_bot(bot_id: str, body: BotUpdateRequest): # 실제 환경: user = Depends(get_current_user)
        """기존 봇의 코드를 업데이트하고 버전을 증가시킵니다."""
        # 실제: bot = bot_repo.get(bot_id)
        bot = mock_db.get(bot_id)
        if not bot:
            raise HTTPException(404, "봇을 찾을 수 없습니다.")
            
        # 1. 코드 검증
        validate_bot_code(body.code, server_config.api.max_bot_code_size)
        
        # 2. 정보 업데이트 및 버전 1 증가
        bot["code"] = body.code
        bot["version"] += 1
        # 실제: bot_repo.update(bot_id, bot)
        
        return {"message": "봇이 성공적으로 업데이트되었습니다.", "bot": bot}

    @app.delete("/api/bots/{bot_id}")
    async def delete_bot(bot_id: str): # 실제 환경: user = Depends(get_current_user)
        """봇을 삭제합니다."""
        # 실제: success = bot_repo.delete(bot_id)
        if bot_id not in mock_db:
            raise HTTPException(404, "봇을 찾을 수 없습니다.")
            
        del mock_db[bot_id]
        return {"message": "봇이 삭제되었습니다."}

    return app
