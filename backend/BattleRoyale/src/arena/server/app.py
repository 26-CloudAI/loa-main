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
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

# RLBossBot 싱글톤 보호용 락. _create_boss_bot은 FastAPI 워커 스레드 풀에서
# 동시에 호출될 수 있으며, reset_for_episode 도중에 다른 요청이 같은 인스턴스를
# 사용하면 _prev_state 등이 오염된다. 락으로 직렬화한다.
_BOSS_BOT_LOCK = threading.Lock()

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
from ..config import BOSS_MAX_USER_BOTS, DEFAULT_CONFIG, boss_battle_config
from . import settings as _settings
from .config import DEFAULT_SERVER_CONFIG, ServerConfig
from .game_session import GameRegistry, GameSession
from .game_views import (
    game_info_from_record,
    game_info_from_state,
    game_result_from_record,
)
from fastapi import Depends
from ..auth.firebase_handler import verify_firebase_token, verify_firebase_token_value
from ..db import init_db, UserRepository, BotRepository, GameRepository
from ..auth.auth_service import FirebaseUserService, decode_token, TokenConfig
from ..ranking.elo import calculate_multiplayer_elo, PlayerResult, EloConfig, get_k_factor, expected_score

from .redis_manager import (
    InMemoryPubSubBroker,
    InMemoryStateStore,
    create_pubsub_broker,
    create_state_store,
)
from .schemas import GameInfo, GameStatus, make_error_message
from .ws_manager import SpectatorManager
from ..mock_auth.router import router as mock_auth_router

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#  콜드스타트 봇 팩토리 (인프로세스용)
# ──────────────────────────────────────────────

# 유저 코드 실행 시 노출할 builtins 화이트리스트(블랙리스트 기반).
# 완전한 샌드박스는 아니지만 open/exec/eval/__import__/input 등을 제거해
# 우발적 파일 IO·동적 import·대화형 차단을 한다. 진정한 격리는 Docker/seccomp가
# 필요하지만 현재 인프라에서는 이 제한이 최소한의 방어선이다.
_FORBIDDEN_BUILTINS = frozenset({
    "open", "exec", "eval", "compile", "__import__",
    "input", "breakpoint", "memoryview",
    "globals", "vars",
})


def _restricted_builtins() -> dict:
    import builtins as _b
    safe = {}
    for name in dir(_b):
        if name.startswith("_"):
            continue
        if name in _FORBIDDEN_BUILTINS:
            continue
        safe[name] = getattr(_b, name)
    return safe


_RESTRICTED_BUILTINS = _restricted_builtins()


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
            local_ns: dict = {"__builtins__": _RESTRICTED_BUILTINS}
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
        except Exception as e:
            logger.warning("봇 %s 액션 실행 오류, STAY 처리: %s", self._bot_id, e, exc_info=True)
            return "STAY"


def _create_filler_bots(count: int, existing_ids: set[str]) -> list[BotInterface]:
    """빈 슬롯을 채우는 AI 봇 생성."""
    from bots.battle_royale.herbivore import HerbivoreBot
    from bots.battle_royale.mad_dog import MadDogBot
    from bots.battle_royale.camper import CamperBot

    bot_classes = [HerbivoreBot, MadDogBot, CamperBot]
    labels = ["AI_초식", "AI_미친개", "AI_존버"]
    fillers = []

    for i in range(count):
        cls_idx = i % len(bot_classes)
        # 이름 충돌 시 suffix를 증가시키며 빈 ID 탐색.
        # (이전 구현은 for 루프 변수 i를 while 내부에서 재할당했는데, 다음 반복에서
        #  range가 원래 시퀀스를 그대로 진행하므로 무한 충돌 가능성이 있었다.)
        suffix = i
        bot_id = f"{labels[cls_idx]}_{suffix:02d}"
        while bot_id in existing_ids:
            suffix += count
            bot_id = f"{labels[cls_idx]}_{suffix:02d}"
        existing_ids.add(bot_id)
        fillers.append(bot_classes[cls_idx](bot_id=bot_id, seed=suffix))

    return fillers


def _create_boss_bot(
    existing_ids: set[str],
    difficulty: str = "상",
    rl_singleton_state: Optional[dict] = None,
) -> BotInterface:
    """
    보스전용 봇 생성. 난이도에 따라 봇 종류가 다름.
      하 → RuleBossEasyBot  (룰베이스, 채굴·생존 중심)
      중 → RuleBossMediumBot (룰베이스, 채굴+전투 균형)
      상 → RLBossBot         (강화학습, GCS 가중치 사용)

    rl_singleton_state: 주어지면 "rl_boss_bot" 키에 RLBossBot 인스턴스를
    캐싱하여 보스전마다 동일 인스턴스를 재사용한다. 리플레이 버퍼/가중치/
    epsilon이 게임 사이에 유지되어 프로덕션 학습이 가능해진다.
    """
    bot_id = "AI_보스"
    existing_ids.add(bot_id)

    if difficulty == "하":
        from bots.boss.rule_boss_bot import RuleBossEasyBot
        return RuleBossEasyBot(bot_id=bot_id, seed=42)

    if difficulty == "중":
        from bots.boss.rule_boss_bot import RuleBossMediumBot
        return RuleBossMediumBot(bot_id=bot_id, seed=42)

    # 상 (기본값): RL 보스봇 + GCS 가중치 — 싱글톤 재사용
    # 학습은 PyTorch(.pt) 포맷, 서빙은 PyTorch가 있으면 동일 포맷을 사용해
    # 학습 결과가 즉시 반영되도록 한다. PyTorch가 없으면 numpy 버전으로 폴백
    # (단, .pt 가중치는 로드되지 않으므로 무작위 초기화 상태로 동작한다).
    import gcs_weights

    # 동시 보스전 요청이 같은 인스턴스를 reset_for_episode하는 경쟁 상태를 방지.
    # 락 내부에서 싱글톤 조회/reset/생성/저장을 모두 직렬화한다.
    with _BOSS_BOT_LOCK:
        if rl_singleton_state is not None:
            cached = rl_singleton_state.get("rl_boss_bot")
            if cached is not None:
                try:
                    cached.reset_for_episode()
                    return cached
                except Exception:
                    logger.exception(
                        "RL 보스봇 싱글톤 reset 실패 — 새 인스턴스 생성"
                    )

        cache = gcs_weights.local_cache_path()
        # 캐시가 없고 GCS가 활성화된 경우 서버 시작 시 다운로드 실패를 재시도
        if not cache.exists() and gcs_weights.enabled():
            logger.info("보스봇 가중치 캐시 없음 — GCS 재다운로드 시도")
            gcs_weights.download()
        weights_path = cache if cache.exists() else None

        # PyTorch 사용 가능 + 가중치가 .pt면 Torch 봇을, 아니면 numpy 봇을 사용.
        use_torch = False
        if weights_path is not None and str(weights_path).endswith(".pt"):
            try:
                import torch  # noqa: F401
                use_torch = True
            except ImportError:
                logger.warning(
                    "PyTorch 가중치(.pt)가 다운로드됐지만 torch 미설치 — "
                    "numpy 보스봇으로 폴백 (학습 가중치 반영 안 됨)"
                )

        if use_torch:
            from bots.boss.rl_boss_bot_torch import RLBossBotTorch
            bot = RLBossBotTorch(
                bot_id=bot_id, seed=0, weights_path=weights_path, device="cpu"
            )
        else:
            from bots.boss.rl_boss_bot import RLBossBot
            bot = RLBossBot(bot_id=bot_id, seed=0, weights_path=weights_path)

        if rl_singleton_state is not None:
            rl_singleton_state["rl_boss_bot"] = bot
            logger.info(
                "RL 보스봇 싱글톤 인스턴스 생성 (%s) — 이후 보스전에서 재사용",
                type(bot).__name__,
            )

        return bot

# ──────────────────────────────────────────────
#  Pydantic 스키마 (데이터 검증용) -> 클라이언트가 보낸 JSON울 파이썬 객체로 변환
# ──────────────────────────────────────────────
class BotCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="봇 이름")
    code: str = Field(..., description="봇 파이썬 코드")
    is_public: bool = Field(False, description="봇 코드 공개 여부")

class BotUpdateRequest(BaseModel):
    code: str = Field(..., description="업데이트할 봇 파이썬 코드")

class UserRegisterRequest(BaseModel):
    username: str = Field(
        ...,
        min_length=3,
        max_length=30,
        pattern=r"^[a-zA-Z0-9_]+$",
        description="사용자 이름 (3-30자, 영문/숫자/밑줄)",
    )
    display_name: Optional[str] = Field(None, max_length=50)

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
    state = {
        "registry": None,
        "spectator_mgr": None,
        "db_conn": None,
        "user_repo": None,
        "bot_repo": None,
        "game_repo": None,
        "firebase_user_svc": None,
        # 보스전(난이도 상)에서 재사용되는 RLBossBot 싱글톤.
        # 매 게임마다 새로 만들면 리플레이 버퍼가 비어 학습이 시작되지 않으므로
        # 한 번 생성한 인스턴스를 모든 보스전에 재활용한다.
        "rl_boss_bot": None,
    }

    # 레이트리밋: IP별 요청 타임스탬프 (슬라이딩 윈도우)
    _rate_limit_store: dict[str, deque] = defaultdict(deque)
    _RATE_LIMIT_MAX = 3       # 최대 요청 수
    _RATE_LIMIT_WINDOW = 60   # 슬라이딩 윈도우 (초)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # GCS에서 최신 보스봇 가중치 다운로드 (BOSS_WEIGHTS_GCS_URI 설정 시)
        import gcs_weights
        if gcs_weights.enabled():
            gcs_weights.download()
            logger.info("보스봇 가중치 GCS에서 로드 완료")

        # 시작
        store = await create_state_store(server_config.redis, use_redis)
        pubsub = await create_pubsub_broker(server_config.redis, use_redis)

        registry = GameRegistry(store, pubsub, server_config)
        spectator_mgr = SpectatorManager(server_config.websocket, pubsub)

        state["registry"] = registry
        state["spectator_mgr"] = spectator_mgr

        def _init_repositories():
            db_conn = None
            try:
                db_conn = init_db()
                user_repo = UserRepository(db_conn)
                bot_repo = BotRepository(db_conn)
                game_repo = GameRepository(db_conn)
                firebase_user_svc = FirebaseUserService(user_repo)
                stale = game_repo.cleanup_stale_games()
                return db_conn, user_repo, bot_repo, game_repo, firebase_user_svc, stale
            except Exception:
                if db_conn is not None:
                    db_conn.close()
                raise

        try:
            loop = asyncio.get_running_loop()
            (
                db_conn,
                user_repo,
                bot_repo,
                game_repo,
                firebase_user_svc,
                stale,
            ) = await asyncio.wait_for(
                loop.run_in_executor(None, _init_repositories),
                timeout=35.0,
            )
            state["db_conn"] = db_conn
            state["user_repo"] = user_repo
            state["bot_repo"] = bot_repo
            state["game_repo"] = game_repo
            state["firebase_user_svc"] = firebase_user_svc

            if stale:
                logger.info("서버 재시작: %d개 미완료 게임을 error 상태로 변경", stale)
        except Exception as e:
            logger.exception("BattleRoyale DB 초기화 실패, DB 없이 기동: %s", e)

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

        # 보스봇 가중치 hot-reload 태스크 (10분 주기, GCS 설정 시에만)
        # download만으로는 캐시 파일만 갱신되고 메모리의 RL 싱글톤은 그대로다.
        # 새 generation을 감지하면 싱글톤을 무효화하여 다음 보스전에서 신규
        # 가중치로 재생성되도록 한다. (락으로 동시 보스전과 직렬화.)
        reload_task = None
        if gcs_weights.enabled():
            _last_generation: list[int | None] = [gcs_weights.get_generation()]

            async def _weights_reload_loop():
                while True:
                    await asyncio.sleep(600)
                    try:
                        gen = gcs_weights.get_generation()
                        if gen is None or gen == _last_generation[0]:
                            continue
                        gcs_weights.download()
                        with _BOSS_BOT_LOCK:
                            if state.get("rl_boss_bot") is not None:
                                state["rl_boss_bot"] = None
                                logger.info(
                                    "보스봇 싱글톤 무효화 — 다음 보스전에서 신규 가중치 로드"
                                )
                        _last_generation[0] = gen
                        logger.info("보스봇 가중치 갱신됨 (generation %s)", gen)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("가중치 hot-reload 실패")

            reload_task = asyncio.create_task(_weights_reload_loop())

        yield

        if state["db_conn"] is not None:
            state["db_conn"].close()

        # 종료
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        if reload_task:
            reload_task.cancel()
            try:
                await reload_task
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

    def _user_repo() -> UserRepository:
        repo = state["user_repo"]
        if repo is None:
            raise HTTPException(503, "DB를 사용할 수 없습니다.")
        return repo

    def _bot_repo() -> BotRepository:
        repo = state["bot_repo"]
        if repo is None:
            raise HTTPException(503, "DB를 사용할 수 없습니다.")
        return repo

    def _game_repo() -> GameRepository:
        repo = state["game_repo"]
        if repo is None:
            raise HTTPException(503, "DB를 사용할 수 없습니다.")
        return repo

    def _firebase_user_svc() -> FirebaseUserService:
        svc = state["firebase_user_svc"]
        if svc is None:
            raise HTTPException(503, "DB를 사용할 수 없습니다.")
        return svc

    def _current_db_user(decoded_token: dict):
        return _firebase_user_svc().get_or_create_user(decoded_token)

    def _decode_auth_token(token: str) -> dict:
        if _settings.ENV != "production":
            config = TokenConfig(secret_key=_settings.JWT_SECRET)
            payload = decode_token(token, config)
            if not payload:
                raise HTTPException(401, "유효하지 않거나 만료된 토큰입니다.")
            return {"uid": payload.get("sub"), "email": payload.get("email", "")}
        return verify_firebase_token_value(token)

    async def _list_owned_game_infos(owner_user_id: int) -> list[GameInfo]:
        registry = _registry()
        infos: list[GameInfo] = []
        for record in _game_repo().list_games_by_owner(owner_user_id):
            state_data = None
            if record.status in (GameStatus.WAITING.value, GameStatus.RUNNING.value):
                state_data = await registry.state_store.get_game_state(record.id)

            if state_data:
                infos.append(game_info_from_state(
                    record.id, state_data, name=record.name, mode=record.mode,
                    created_at=record.created_at,
                ))
                continue

            participants = _game_repo().get_participants(record.id)
            infos.append(game_info_from_record(record, participants))
        return infos

    async def _resolve_owned_game_info(game_id: str, owner_user_id: int) -> Optional[GameInfo]:
        registry = _registry()
        record = _game_repo().get_game_by_owner(game_id, owner_user_id)
        if not record:
            return None

        state_data = await registry.state_store.get_game_state(game_id)
        if state_data:
            return game_info_from_state(
                game_id, state_data, name=record.name, mode=record.mode,
                created_at=record.created_at,
            )

        participants = _game_repo().get_participants(game_id)
        return game_info_from_record(record, participants)

    # ── REST API ──

    @app.post("/api/games")
    async def create_game(
        request: Request,
        body: dict,
        user: dict = Depends(verify_firebase_token),
    ):
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
        repo = _game_repo()
        db_user = _current_db_user(user)
        bots_data = body.get("bots", [])
        tick_interval = body.get("tick_interval", 0.05)
        seed = body.get("seed")
        fill_with_ai = body.get("fill_with_ai", True)
        min_bots = body.get("min_bots", 4)
        mode = body.get("mode", "battle-royale")
        difficulty = body.get("difficulty", "상")  # 보스전 난이도: 하/중/상
        name = body.get("name", "").strip() or None

        # 봇 코드 크기 검증
        max_size = server_config.api.max_bot_code_size
        for b in bots_data:
            if len(b.get("code", "")) > max_size:
                raise HTTPException(
                    400,
                    f"봇 {b.get('bot_id', '?')} 코드가 {max_size}B를 초과합니다.",
                )

        # 유저 봇을 DB에 저장하여 bot_id 확보
        _MODE_LABEL = {"battle-royale": "배틀로얄", "boss": "보스전"}
        mode_label = _MODE_LABEL.get(mode, mode)
        game_description = f"{mode_label} · {name}" if name else mode_label

        bot_repo_inst = _bot_repo()
        bot_name_to_db_id: dict[str, int] = {}
        for b in bots_data:
            bot_name = b["bot_id"]
            is_public = bool(b.get("is_public", True))
            new_bot = bot_repo_inst.create(
                user_id=db_user.id,
                name=bot_name,
                code=b["code"],
                is_public=is_public,
                description=game_description,
            )
            bot_name_to_db_id[bot_name] = new_bot.id

        # 모드별 게임 설정 (보스전은 지역 config 오버라이드, 전역 설정 불변)
        game_cfg = boss_battle_config() if mode == "boss" else DEFAULT_CONFIG

        # 게임 세션 생성
        session = registry.create_game(
            game_repo=repo,
            game_config=game_cfg,
            tick_interval=tick_interval,
            seed=seed,
        )

        # 유저 봇 등록
        bot_interfaces: list[BotInterface] = []
        existing_ids: set[str] = set()
        # (bot_name, is_ai_filler, is_boss_bot)
        participant_specs: list[tuple[str, bool, bool]] = []

        for b in bots_data:
            bot = InProcessBot(b["bot_id"], b["code"])
            bot_interfaces.append(bot)
            existing_ids.add(b["bot_id"])
            participant_specs.append((b["bot_id"], False, False))

        if mode == "boss":
            # 보스전: 유저 봇 1~BOSS_MAX_USER_BOTS개 + 보스봇 1개 (난이도별)
            if not (1 <= len(bot_interfaces) <= BOSS_MAX_USER_BOTS):
                raise HTTPException(
                    400,
                    f"보스전은 봇 1~{BOSS_MAX_USER_BOTS}개를 등록할 수 있습니다.",
                )
            boss_bot = _create_boss_bot(
                existing_ids,
                difficulty=difficulty,
                rl_singleton_state=state,
            )
            bot_interfaces.append(boss_bot)
            participant_specs.append((boss_bot.bot_id, False, True))
        elif fill_with_ai and len(bot_interfaces) < min_bots:
            # 배틀로얄: AI 봇으로 빈 슬롯 채우기
            filler_count = min_bots - len(bot_interfaces)
            fillers = _create_filler_bots(filler_count, existing_ids)
            bot_interfaces.extend(fillers)
            participant_specs.extend((bot.bot_id, True, False) for bot in fillers)

        if len(bot_interfaces) < 2:
            raise HTTPException(400, "최소 2개의 봇이 필요합니다.")

        if not name:
            count = repo.count_games_by_mode(db_user.id, mode)
            mode_label = {"battle-royale": "배틀로얄", "boss": "보스전"}.get(mode, mode)
            name = f"새 {mode_label} {count + 1}"

        repo.create_game(
            session.game_id,
            owner_user_id=db_user.id,
            total_bots=len(bot_interfaces),
            seed=seed,
            name=name,
            mode=mode,
        )
        for bot_name, is_ai_filler, is_boss_bot in participant_specs:
            db_bot_id = bot_name_to_db_id.get(bot_name) if not is_ai_filler and not is_boss_bot else None
            repo.add_participant(
                session.game_id,
                bot_name,
                bot_id=db_bot_id,
                is_ai_filler=is_ai_filler,
                is_boss_bot=is_boss_bot,
            )

        session.register_bots(bot_interfaces)
        await session.start()

        # 게임 완료 후 ELO 업데이트 (백그라운드)
        task = asyncio.create_task(
            _update_elo_after_game(session.game_id, db_user.id)
        )
        task.add_done_callback(
            lambda t: logger.error("ELO 업데이트 오류: %s", t.exception()) if t.exception() else None
        )

        return session.get_info().to_dict()

    async def _update_elo_after_game(game_id: str, owner_user_id: int) -> None:
        """게임 완료를 기다렸다가 유저 ELO를 갱신한다."""
        # DB에 finished 상태가 기록될 때까지 폴링 (session status 대신 DB 기준)
        for _ in range(300):
            await asyncio.sleep(1)
            game_record = _game_repo().get_game(game_id)
            if game_record and game_record.status == GameStatus.FINISHED.value:
                break
        else:
            return

        # participant final_rank가 모두 기록될 때까지 대기 (최대 5초)
        participants: list = []
        real_participants = []
        for _ in range(10):
            participants = _game_repo().get_participants(game_id)
            real_participants = [
                p for p in participants
                if not p.is_ai_filler and not p.is_boss_bot
                and p.bot_id and p.final_rank
            ]
            if real_participants:
                break
            await asyncio.sleep(0.5)

        # 보스전 결과 기록 — real_participants early-return 전에 처리해야 보스 승리도 기록됨
        if game_record and game_record.mode == "boss":
            boss_participants = [
                p for p in participants if p.is_boss_bot and p.final_rank
            ]
            user_ranked = [
                p for p in participants
                if not p.is_ai_filler and not p.is_boss_bot and p.final_rank
            ]
            if boss_participants and user_ranked:
                boss_rank = boss_participants[0].final_rank
                best_user_rank = min(p.final_rank for p in user_ranked)
                if boss_rank != best_user_rank:  # 동점(동일 rank)이면 draw — NULL 유지
                    try:
                        _game_repo().update_game_boss_result(
                            game_id, boss_won=(boss_rank < best_user_rank)
                        )
                    except Exception:
                        logger.exception(
                            "보스전 결과 기록 실패 game=%s", game_id
                        )

        if not real_participants:
            return

        bot_repo_inst = _bot_repo()
        user_repo = _user_repo()

        # bot_id → user_id 매핑
        bot_user_map: dict[int, int] = {}
        for p in real_participants:
            bot = bot_repo_inst.get_by_id(p.bot_id)
            if bot:
                bot_user_map[p.bot_id] = bot.user_id

        # 유저별 최고 순위 집계
        user_best_rank: dict[int, int] = {}
        for p in real_participants:
            uid = bot_user_map.get(p.bot_id)
            if uid is None:
                continue
            if uid not in user_best_rank or p.final_rank < user_best_rank[uid]:
                user_best_rank[uid] = p.final_rank

        if not user_best_rank:
            return

        winner_rank = min(user_best_rank.values())

        # 봇 테이블 전적 업데이트 (전체 1위 = 승리)
        for p in real_participants:
            if bot_user_map.get(p.bot_id) is None:
                continue
            bot_repo_inst.record_game_result(p.bot_id, p.final_rank == 1)

        if len(user_best_rank) >= 2:
            # 다수 유저: 표준 멀티플레이어 ELO
            elo_config = EloConfig()
            player_results = []
            for uid, rank in user_best_rank.items():
                u = user_repo.get_by_id(uid)
                if u:
                    player_results.append(PlayerResult(uid, float(u.elo), u.games_played, rank))
            changes = calculate_multiplayer_elo(player_results, elo_config)
            for change in changes:
                won = user_best_rank.get(change.player_id, 999) == winner_rank
                user_repo.update_elo(change.player_id, int(change.rating_after), won)
        else:
            # 1인 vs AI: AI 평균 레이팅(1000) 기준 ELO 계산
            uid = next(iter(user_best_rank))
            rank = user_best_rank[uid]
            u = user_repo.get_by_id(uid)
            if not u:
                return
            won = (rank == 1)
            k = get_k_factor(u.games_played)
            exp = expected_score(float(u.elo), 1000.0)
            actual = 1.0 if won else 0.0
            delta = k * (actual - exp)
            new_elo = max(100, int(u.elo + delta))
            user_repo.update_elo(uid, new_elo, won)

        logger.info("게임 %s ELO 업데이트 완료: %d명", game_id, len(user_best_rank))

    @app.get("/api/games")
    async def list_games(user: dict = Depends(verify_firebase_token)):
        """현재 로그인 사용자의 게임 기록 목록."""
        db_user = _current_db_user(user)
        return [g.to_dict() for g in await _list_owned_game_infos(db_user.id)]

    @app.get("/api/games/{game_id}")
    async def get_game(game_id: str, user: dict = Depends(verify_firebase_token)):
        """게임 정보."""
        db_user = _current_db_user(user)
        info = await _resolve_owned_game_info(game_id, db_user.id)
        if not info:
            raise HTTPException(404, "게임을 찾을 수 없습니다.")
        return info.to_dict()

    @app.get("/api/games/{game_id}/result")
    async def get_game_result(game_id: str, user: dict = Depends(verify_firebase_token)):
        """게임 결과."""
        db_user = _current_db_user(user)
        registry = _registry()
        record = _game_repo().get_game_by_owner(game_id, db_user.id)
        if not record:
            raise HTTPException(404, "게임을 찾을 수 없습니다.")

        session = registry.get_game(game_id)

        if session and session.status != GameStatus.FINISHED:
            raise HTTPException(400, "게임이 아직 진행 중입니다.")

        result = await registry.state_store.get_game_result(game_id)
        if result:
            return result

        state_data = await registry.state_store.get_game_state(game_id)
        if state_data:
            if record.status != GameStatus.FINISHED.value:
                raise HTTPException(400, "게임이 아직 진행 중입니다.")
            participants = _game_repo().get_participants(game_id)
            return game_result_from_record(record, participants)

        if record.status != GameStatus.FINISHED.value:
            raise HTTPException(400, "게임이 아직 진행 중입니다.")

        participants = _game_repo().get_participants(game_id)
        return game_result_from_record(record, participants)

    @app.get("/api/games/{game_id}/replay")
    async def get_game_replay(game_id: str, user: dict = Depends(verify_firebase_token)):
        """게임 리플레이 전체 프레임을 반환."""
        db_user = _current_db_user(user)
        if not _game_repo().get_game_by_owner(game_id, db_user.id):
            raise HTTPException(404, "게임을 찾을 수 없습니다.")
        registry = _registry()
        frames = await registry.state_store.get_replay_frames(game_id)
        if not frames:
            raise HTTPException(404, "리플레이 데이터가 없습니다.")
        result = await registry.state_store.get_game_result(game_id)
        return {
            "game_id": game_id,
            "total_frames": len(frames),
            "frames": frames,
            "result": result,
        }

    @app.delete("/api/games/{game_id}")
    async def stop_game(game_id: str, user: dict = Depends(verify_firebase_token)):
        """게임을 강제 종료."""
        db_user = _current_db_user(user)
        if not _game_repo().get_game_by_owner(game_id, db_user.id):
            raise HTTPException(404, "게임을 찾을 수 없습니다.")
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
        token = websocket.query_params.get("token")
        if not token:
            await websocket.close(code=4001, reason="인증 토큰이 없습니다.")
            return

        try:
            decoded = _decode_auth_token(token)
            db_user = _current_db_user(decoded)
        except HTTPException:
            await websocket.close(code=4001, reason="유효하지 않은 인증 토큰입니다.")
            return

        if not _game_repo().get_game_by_owner(game_id, db_user.id):
            await websocket.close(code=4004, reason="게임을 찾을 수 없습니다.")
            return

        session = registry.get_game(game_id)
        current = await registry.state_store.get_game_state(game_id)
        if not session and not current:
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
        bot = repo.create(user_id=db_user.id, name=body.name, code=body.code, is_public=body.is_public)
        return {"message": "봇이 성공적으로 등록되었습니다.", "bot": {"id": bot.id, "name": bot.name, "version": bot.version, "is_public": bot.is_public}}

    @app.get("/api/bots")
    async def list_my_bots(user: dict = Depends(verify_firebase_token)):
        db_user = _firebase_user_svc().get_or_create_user(user)
        bots = _bot_repo().get_by_user(db_user.id)
        return {"bots": [
            {
                "id": b.id,
                "name": b.name,
                "version": b.version,
                "is_public": b.is_public,
                "wins": b.wins,
                "losses": b.losses,
                "games_played": b.games_played,
                "win_rate": round(b.win_rate, 3),
            }
            for b in bots
        ]}

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

    @app.patch("/api/bots/{bot_id}/visibility")
    async def set_bot_visibility(
        bot_id: int,
        body: dict,
        user: dict = Depends(verify_firebase_token),
    ):
        """봇 공개 여부를 변경한다."""
        repo = _bot_repo()
        bot = repo.get_by_id(bot_id)
        if not bot or not bot.is_active:
            raise HTTPException(404, "봇을 찾을 수 없습니다.")
        db_user = _firebase_user_svc().get_or_create_user(user)
        if bot.user_id != db_user.id:
            raise HTTPException(403, "접근 권한이 없습니다.")
        is_public = bool(body.get("is_public", False))
        repo.set_public(bot_id, is_public)
        return {"message": "변경되었습니다.", "is_public": is_public}

    # ── 랭킹 API ──

    @app.get("/api/rankings")
    async def get_rankings():
        """ELO 순 전체 유저 랭킹을 반환한다. (인증 불필요)"""
        users = _user_repo().get_rankings(limit=100)
        return {
            "rankings": [
                {
                    "rank": idx + 1,
                    "user_id": u.id,
                    "username": u.username,
                    "display_name": u.display_name,
                    "elo": u.elo,
                    "wins": u.wins,
                    "losses": u.losses,
                    "games_played": u.games_played,
                    "win_rate": round(u.wins / u.games_played, 3) if u.games_played > 0 else 0.0,
                }
                for idx, u in enumerate(users)
            ]
        }

    @app.post("/api/users/register", status_code=201)
    async def register_user(
        body: UserRegisterRequest,
        user: dict = Depends(verify_firebase_token),
    ):
        """Firebase 인증 후 DB에 유저를 등록한다. (최초 1회)"""
        firebase_uid = user.get("uid") or user.get("user_id", "")
        repo = _user_repo()

        if repo.get_by_firebase_uid(firebase_uid):
            raise HTTPException(409, "이미 등록된 계정입니다.")
        if repo.username_exists(body.username):
            raise HTTPException(409, "이미 사용 중인 사용자 이름입니다.")

        auth_provider = user.get("firebase", {}).get("sign_in_provider", "password")
        display_name = body.display_name or body.username

        new_user = repo.create(
            firebase_uid=firebase_uid,
            username=body.username,
            display_name=display_name,
            email=user.get("email", ""),
            auth_provider=auth_provider,
            photo_url=user.get("picture"),
        )

        return {
            "id": new_user.id,
            "username": new_user.username,
            "display_name": new_user.display_name,
            "email": new_user.email,
            "role": new_user.role,
            "elo": new_user.elo,
        }

    @app.get("/api/me")
    async def get_current_user(user: dict = Depends(verify_firebase_token)):
        """현재 인증된 유저의 DB 정보를 반환한다."""
        firebase_uid = user.get("uid") or user.get("user_id", "")
        db_user = _user_repo().get_by_firebase_uid(firebase_uid)
        if not db_user:
            raise HTTPException(404, "등록되지 않은 유저입니다.")
        return {
            "id": db_user.id,
            "username": db_user.username,
            "display_name": db_user.display_name,
            "email": db_user.email,
            "role": db_user.role,
            "elo": db_user.elo,
        }

    @app.patch("/api/me")
    async def update_my_profile(
        body: dict,
        user: dict = Depends(verify_firebase_token),
    ):
        """닉네임(display_name) 변경."""
        firebase_uid = user.get("uid") or user.get("user_id", "")
        db_user = _user_repo().get_by_firebase_uid(firebase_uid)
        if not db_user:
            raise HTTPException(404, "등록되지 않은 유저입니다.")
        display_name = body.get("display_name", "").strip()
        if not display_name:
            raise HTTPException(400, "닉네임을 입력해주세요.")
        if len(display_name) > 20:
            raise HTTPException(400, "닉네임은 20자 이하로 입력해주세요.")
        _user_repo().update_display_name(db_user.id, display_name)
        return {"message": "닉네임이 변경되었습니다.", "display_name": display_name}

    @app.get("/api/users/check-username")
    async def check_username(username: str):
        """username 사용 가능 여부를 반환한다. (인증 불필요)"""
        available = not _user_repo().username_exists(username)
        return {"available": available}

    @app.get("/api/users/{user_id}/bots")
    async def get_user_public_bots(user_id: int, request: Request):
        """특정 유저의 봇 목록을 반환한다. 본인이면 비공개 코드도 반환."""
        user = _user_repo().get_by_id(user_id)
        if not user or not user.is_active:
            raise HTTPException(404, "유저를 찾을 수 없습니다.")

        # 본인 여부 확인 (토큰이 있으면 검증, 없으면 타인으로 처리)
        is_owner = False
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                decoded = _decode_auth_token(auth_header[7:])
                requester = _firebase_user_svc().get_or_create_user(decoded)
                is_owner = (requester.id == user_id)
            except Exception:
                pass

        bots = _bot_repo().get_by_user(user_id, active_only=True)
        _MODE_LABEL = {
            "battle-royale": "배틀로얄",
            "boss": "보스전",
            "mock-stocks": "모의주식",
        }
        bot_list = []
        for b in bots:
            game_info = _game_repo().get_game_info_for_bot(b.id)
            game_mode = _MODE_LABEL.get(game_info["mode"], game_info["mode"]) if game_info else None
            game_name = game_info["name"] if game_info else None
            show_code = b.is_public or is_owner
            bot_list.append({
                "id": b.id,
                "name": b.name,
                "game_mode": game_mode,
                "game_name": game_name,
                "code": b.code if show_code else None,
                "is_public": b.is_public,
                "version": b.version,
                "wins": b.wins,
                "losses": b.losses,
                "games_played": b.games_played,
                "created_at": b.created_at,
                "updated_at": b.updated_at,
            })
        return {
            "user": {
                "user_id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "elo": user.elo,
                "wins": user.wins,
                "losses": user.losses,
                "games_played": user.games_played,
            },
            "bots": bot_list,
        }

    return app
