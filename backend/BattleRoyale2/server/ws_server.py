"""BattleRoyale2 WebSocket 서버.

Godot 클라이언트와 PROTOCOL.md (loa-battleroyale-game 레포) 의 메시지를 주고받는다.
v0.1: 단일 매치, 단일 클라이언트, 봇 객체는 서버에서 인스턴스화 후 매 STATE 마다 get_action 호출.

핵심 흐름
    C → S  HELLO
    S → C  MATCH_CONFIG (bots 목록 + map / seed / duration)
    S → C  MATCH_START
    매 100ms (반복):
        C → S  STATE (각 봇 시점별 state)
        S → C  ACTIONS (각 봇별 action dict)
    C → S  EVENT (kill / pickup / zone 등 발생 시)
    C → S  MATCH_END (최종 순위)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
import uuid
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from BattleRoyale2.bots import HerbivoreBot, MadDogBot, CamperBot
from BattleRoyale2.server.inprocess_bot import InProcessBot2
from BattleRoyale2.server.runner_manager import get_runner_manager
from BattleRoyale2.src.arena.bot_interface import BattleRoyale2DBot

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "0.1"
GAME_MODE = "battleroyale2"   # games.mode 값 (기존 'battle-royale' 과 구분)
TARGET_BOT_COUNT = 4          # 유저 봇 + AI 채움으로 맞출 기본 총 봇 수

# game_id → 유저 봇 코드 목록 [{bot_id, name, code}]. POST /api/games 에서 저장,
# WS MATCH_CONFIG 빌드 시 조회. (인메모리 — 서버 재시작 시 소실, v0.1 단순화)
_GAME_CODE: dict[str, list[dict]] = {}
# game_id → 총 봇 수 (내 봇 + AI 채움). POST /api/games 에서 저장.
_GAME_BOT_COUNT: dict[str, int] = {}

# AI 채움용 봇 종류 (유저 봇 외 빈 슬롯). 순서대로 순환.
_AI_FILLERS: list[tuple[str, type[BattleRoyale2DBot]]] = [
    ("초식봇", HerbivoreBot),
    ("미친개봇", MadDogBot),
    ("존버봇", CamperBot),
]

# 기존 battle_royale 의 GameRepository 재활용 (games / game_participants 테이블 공유).
# 통합 서버(run_server.py)에서 virtual 'src' 패키지가 battle_royale/src 를 가리키므로
# 'from src.arena.db import ...' 가 동작. 단독 실행 등으로 import 실패 시 저장 비활성(None).
_GAME_REPO = None          # GameRepository 인스턴스
_GAME_REPO_TRIED = False   # 한 번 시도했는지 (실패 시 재시도 안 함)


def _get_game_repo():
    """GameRepository 를 lazy 하게 1회 초기화. 실패하면 None (저장 비활성)."""
    global _GAME_REPO, _GAME_REPO_TRIED
    if _GAME_REPO_TRIED:
        return _GAME_REPO
    _GAME_REPO_TRIED = True
    try:
        from src.arena.db import init_db, GameRepository  # type: ignore
        conn = init_db()
        _GAME_REPO = GameRepository(conn)
        logger.info("[BR2] GameRepository 연결됨 (DB 저장 활성)")
    except Exception as e:  # noqa: BLE001
        logger.warning("[BR2] DB 연결 실패 — 매치 기록 저장 비활성 (%s)", e)
        _GAME_REPO = None
    return _GAME_REPO


# 리플레이/라이브 프레임 저장소 (기존 battle_royale StateStore 재활용).
# v0.1 은 InMemoryStateStore. 통합 서버에서 virtual 'src' → battle_royale/src 매핑.
_STATE_STORE = None
_STATE_STORE_TRIED = False
_STATE_STORE_LOCK = None    # asyncio.Lock (이벤트 루프 안에서 lazy 생성)

# match_id → 권위 세션의 id(). 첫 WS 연결이 권위. (PROTOCOL.md §3.13)
_AUTHORITATIVE: dict[str, int] = {}

# match_id → 관전 세션 집합 (C2 라이브 관전). 권위 세션의 FRAME 을 여기로 중계.
_SPECTATORS: dict[str, set["MatchSession"]] = {}


async def _pump_spectator(match_id: str, session: "MatchSession") -> None:
    """관전 세션에 아직 안 보낸 store 프레임을 순서대로 전송.
    catch-up(중간 합류)·live tail 공용 — relay_idx 로 진행 위치를 추적해 누락/중복 방지.
    coins/items 가 델타라 init+누적프레임을 순서대로 재생해야 월드가 복원된다.
    세션별 락으로 join-catchup 과 broadcast 동시 호출을 직렬화."""
    store = await _get_state_store()
    if store is None:
        return
    if session._relay_lock is None:
        session._relay_lock = asyncio.Lock()
    async with session._relay_lock:
        frames = await store.get_replay_frames(match_id)
        if session.relay_idx >= len(frames):
            return
        for fr in frames[session.relay_idx:]:
            if fr.get("kind") == "init":
                await session.send({"type": "FRAME_INIT", "data": fr.get("data", {})})
            else:
                await session.send({"type": "FRAME", "tick": fr.get("tick", 0),
                                    "data": fr.get("data", {})})
        session.relay_idx = len(frames)


async def _broadcast_frame(match_id: str) -> None:
    """권위 세션이 새 프레임을 기록한 직후, 등록된 모든 관전자에게 중계."""
    specs = _SPECTATORS.get(match_id)
    if not specs:
        return
    for s in list(specs):
        try:
            await _pump_spectator(match_id, s)
        except Exception:  # noqa: BLE001 — 끊긴 관전 소켓 제거
            specs.discard(s)


def _on_runner_exit(match_id: str, rc: int, reason: str) -> None:
    """헤드리스 러너가 비정상 종료(crash/timeout)했을 때 reaper 스레드에서 호출되는 콜백.
    stuck 게임을 DB에서 종료 처리(status='error')해 '진행 중' 상태로 박제되는 것을 막는다.
    reaper 는 별도 스레드지만 DB 연결(sqlite check_same_thread=False / psycopg2)은 동기 핸들러와
    이미 공유 중이라 기존 동시성 모델과 동일하다. 정상 종료(rc=0)는 reaper 가 콜백을 호출하지 않는다."""
    repo = _get_game_repo()
    if repo is None:
        return
    try:
        changed = repo.update_game_abandoned(match_id, end_reason="runner_%s" % reason)
        if changed:
            logger.warning("[BR2] 러너 종료로 게임 종료 처리 match=%s rc=%s reason=%s",
                           match_id, rc, reason)
        else:
            logger.info("[BR2] 러너 종료 콜백 match=%s — 이미 종결된 게임(스킵)", match_id)
    except Exception:  # noqa: BLE001 — DB 오류가 reaper 스레드를 죽이지 않도록 흡수
        logger.exception("[BR2] 러너 종료 DB 처리 실패 match=%s", match_id)


async def _get_state_store():
    """리플레이/라이브 프레임 저장소를 lazy 하게 1회 초기화(비동기).

    USE_REDIS=true 면 RedisStateStore(연결 필요) — 프레임이 Redis 에 영속되어 인스턴스
    재시작·멀티 인스턴스에서도 유지된다. USE_REDIS=false(기본/개발/테스트) 면 InMemoryStateStore.
    Redis 연결 실패 시 팩토리가 InMemory 로 폴백한다.

    sub-app 으로 mount 되면 lifespan 이 전파되지 않으므로(run_server 참고) startup 대신
    첫 사용 시점에 비동기로 연결한다. 호출부가 모두 async 라 await 안전."""
    global _STATE_STORE, _STATE_STORE_TRIED, _STATE_STORE_LOCK
    if _STATE_STORE_TRIED:
        return _STATE_STORE
    if _STATE_STORE_LOCK is None:
        _STATE_STORE_LOCK = asyncio.Lock()
    async with _STATE_STORE_LOCK:
        if _STATE_STORE_TRIED:           # 락 대기 중 다른 코루틴이 먼저 초기화했을 수 있음
            return _STATE_STORE
        try:
            from src.arena.server.redis_manager import create_state_store  # type: ignore
            from src.arena.server.config import RedisConfig  # type: ignore
            from src.arena.server.settings import USE_REDIS  # type: ignore
            _STATE_STORE = await create_state_store(RedisConfig(), USE_REDIS)
            logger.info("[BR2] StateStore 초기화 (redis=%s)", USE_REDIS)
        except Exception as e:  # noqa: BLE001
            logger.warning("[BR2] StateStore 로드 실패 — 프레임 기록 비활성 (%s)", e)
            _STATE_STORE = None
        _STATE_STORE_TRIED = True
    return _STATE_STORE


# ---------- 인증 (토큰 → users.id). battle_royale 인프라 재사용 ----------
_USER_SVC = None
_USER_SVC_TRIED = False


def _get_user_svc():
    """FirebaseUserService 를 lazy 초기화. GameRepository 와 같은 conn 사용. 실패 시 None."""
    global _USER_SVC, _USER_SVC_TRIED
    if _USER_SVC_TRIED:
        return _USER_SVC
    _USER_SVC_TRIED = True
    try:
        from src.arena.db import init_db  # type: ignore
        from src.arena.db.user_repo import UserRepository  # type: ignore
        from src.arena.auth.auth_service import FirebaseUserService  # type: ignore
        _USER_SVC = FirebaseUserService(UserRepository(init_db()))
        logger.info("[BR2] FirebaseUserService 연결됨 (인증 활성)")
    except Exception as e:  # noqa: BLE001
        logger.warning("[BR2] 인증 서비스 로드 실패 (%s)", e)
        _USER_SVC = None
    return _USER_SVC


def _decode_token(token: str) -> dict | None:
    """Bearer 토큰 디코드. battle_royale verify_firebase_token_value 재사용. 실패 시 None."""
    try:
        from src.arena.auth.firebase_handler import verify_firebase_token_value  # type: ignore
        return verify_firebase_token_value(token)
    except Exception:  # noqa: BLE001
        return None


def _is_runner_token(token: str | None) -> bool:
    """서버 헤드리스 러너(C2)용 공유 시크릿 검증. BR2_RUNNER_SECRET 미설정 시 항상 False
    (= 기능 비활성 → 인증 동작 불변). 설정된 경우에만 동일 토큰을 러너로 허용."""
    secret = os.environ.get("BR2_RUNNER_SECRET", "").strip()
    return bool(secret) and token == secret


def _safe_rollback(repo) -> None:
    """PostgreSQL 트랜잭션 abort 상태(오류 후 'transaction is aborted') 복구.
    오류를 삼킨 뒤 rollback 을 안 하면 같은 공유 커넥션의 이후 모든 쿼리가 실패한다.
    SQLite/None 은 무해(rollback 은 no-op 또는 미존재) — 예외는 무시."""
    try:
        conn = getattr(repo, "conn", None)
        if conn is not None:
            conn.rollback()
    except Exception:  # noqa: BLE001
        pass


def _bearer(req_or_headers) -> str | None:
    auth = ""
    try:
        auth = req_or_headers.headers.get("Authorization", "") if hasattr(req_or_headers, "headers") else ""
    except Exception:  # noqa: BLE001
        auth = ""
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):]
    return None


def _resolve_owner_id(token: str | None) -> int | None:
    """토큰 → users.id(int). 토큰 없거나 검증 실패 시 None."""
    if not token:
        return None
    decoded = _decode_token(token)
    if decoded is None:
        return None
    svc = _get_user_svc()
    if svc is None:
        return None
    try:
        user = svc.get_or_create_user(decoded)
        return user.id
    except Exception:  # noqa: BLE001
        logger.exception("[BR2] owner 해석 실패")
        _safe_rollback(getattr(svc, "users", None))   # user 커넥션 abort 복구
        return None


# ---------- 게임 스펙(유저 코드 + 봇 수) 영속: games.config_json ----------
def _spec_config_json(user_bots: list[dict], bot_count: int) -> str:
    return json.dumps({"user_bots": user_bots, "bot_count": bot_count}, separators=(",", ":"))


def _load_game_spec(match_id: str) -> tuple[list[dict], int]:
    """이 게임의 (user_bots, bot_count). 인메모리 캐시 우선, 없으면 DB config_json 에서 로드.
    다중 인스턴스에서 POST 와 WS 가 다른 프로세스여도 DB 로 복원 가능."""
    user_bots = _GAME_CODE.get(match_id)
    bot_count = _GAME_BOT_COUNT.get(match_id)
    if user_bots is not None and bot_count is not None:
        return user_bots, bot_count
    # DB 폴백 — games.config_json 직접 조회 (GameRecord dataclass 엔 config_json 미포함).
    repo = _get_game_repo()
    if repo is not None:
        try:
            cur = repo._execute("SELECT config_json FROM games WHERE id = ?", (match_id,))
            row = cur.fetchone()
            cfg = row["config_json"] if row else None
            if cfg:
                # SQLite: TEXT(str) / PostgreSQL: JSONB(psycopg2 가 dict 로 디코드) 모두 대응.
                parsed = cfg if isinstance(cfg, (dict, list)) else json.loads(cfg)
                ub = parsed.get("user_bots") or []
                bc = int(parsed.get("bot_count") or TARGET_BOT_COUNT)
                _GAME_CODE[match_id] = ub
                _GAME_BOT_COUNT[match_id] = bc
                return ub, bc
        except Exception:  # noqa: BLE001
            logger.exception("[BR2] config_json 로드 실패: %s", match_id)
            _safe_rollback(repo)
    return (user_bots or []), (bot_count or TARGET_BOT_COUNT)

# bot_id → 봇 클래스 매핑. ws_server 는 이 매핑으로 인스턴스 생성.
BOT_CLASS_BY_ID: dict[str, type[BattleRoyale2DBot]] = {
    "bot_a": HerbivoreBot,
    "bot_b": MadDogBot,
    "bot_c": CamperBot,
}

DEFAULT_BOT_FACTORY: list[tuple[str, str]] = [
    # (bot_id, display_name) — 매치 진입 시 이 목록대로 봇 인스턴스 생성.
    # 추후 프론트엔드에서 N 마리 지정 시 같은 종류는 인덱스만 늘려서 운영 ("초식봇 2", ...).
    ("bot_a", "초식봇 1"),
    ("bot_b", "미친개봇 1"),
    ("bot_c", "존버봇 1"),
]


def _build_bots(spec: list[tuple[str, str]], seed: int | None = None) -> dict[str, BattleRoyale2DBot]:
    """bot_id 별로 BOT_CLASS_BY_ID 매핑에 따라 봇 인스턴스 생성. 매핑 없으면 HerbivoreBot 폴백."""
    rng_seed = seed if seed is not None else 0
    bots: dict[str, BattleRoyale2DBot] = {}
    for i, (bot_id, _name) in enumerate(spec):
        cls = BOT_CLASS_BY_ID.get(bot_id, HerbivoreBot)
        bots[bot_id] = cls(bot_id, seed=rng_seed + i)
    return bots


def _validate_action(action: Any) -> dict[str, Any]:
    """봇이 반환한 action 을 안전하게 정규화. 잘못된 키/타입은 기본값으로 치환."""
    def vec(value: Any, default: list[float]) -> list[float]:
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return default
        try:
            return [float(value[0]), float(value[1])]
        except (TypeError, ValueError):
            return default

    if not isinstance(action, dict):
        action = {}
    return {
        "move_dir": vec(action.get("move_dir"), [0.0, 0.0]),
        "aim_dir": vec(action.get("aim_dir"), [1.0, 0.0]),
        "attack": bool(action.get("attack", False)),
        "guard": bool(action.get("guard", False)),
        "dash": bool(action.get("dash", False)),
        "pickup": bool(action.get("pickup", False)),
        "use_potion": bool(action.get("use_potion", False)),
    }


class MatchSession:
    """단일 매치 세션. WebSocket 하나당 하나."""

    def __init__(self, ws: WebSocket, match_id: str):
        self.ws = ws
        self.match_id = match_id
        self.bots: dict[str, BattleRoyale2DBot] = {}
        self.bot_spec: list[tuple[str, str]] = list(DEFAULT_BOT_FACTORY)
        self.started = False
        self.ended = False
        self.match_info: dict[str, Any] = {}
        self.authoritative = False   # 첫 연결만 True — FRAME 기록 권위
        self.user_bot_ids: set = set()   # 유저 제출 봇 id (participant is_ai_filler 구분용)
        self.relay_idx = 0           # 관전 세션: 이미 중계받은 store 프레임 수
        self._relay_lock = None      # asyncio.Lock (lazy) — 중계 직렬화

    async def send(self, payload: dict[str, Any]) -> None:
        await self.ws.send_text(json.dumps(payload, separators=(",", ":")))

    async def send_match_config(self, seed: int = 0) -> None:
        self.bots, self.bot_spec = self._assemble_bots(seed)
        await self.send({
            "type": "MATCH_CONFIG",
            "data": {
                "match_id": self.match_id,
                "seed": seed,
                "duration": 180,
                "bots": [
                    {"id": bid, "display_name": name}
                    for bid, name in self.bot_spec
                ],
            },
        })

    def _assemble_bots(self, seed: int) -> tuple[dict[str, BattleRoyale2DBot], list[tuple[str, str]]]:
        """이 매치(game_id) 의 유저 제출 봇 + AI 채움 봇 구성.
        유저 코드가 없으면 기본 AI 3종(DEFAULT_BOT_FACTORY)으로 폴백.
        AI 채움은 초식/미친개/존버 중 랜덤 선택, 총 봇 수는 config_json/캐시 기준."""
        user_bots, bot_count = _load_game_spec(self.match_id)
        if not user_bots:
            bots = _build_bots(list(DEFAULT_BOT_FACTORY), seed=seed)
            return bots, list(DEFAULT_BOT_FACTORY)

        bots: dict[str, BattleRoyale2DBot] = {}
        spec: list[tuple[str, str]] = []
        self.user_bot_ids = set()
        for entry in user_bots:
            bid = entry["bot_id"]
            name = entry.get("name", bid)
            bots[bid] = InProcessBot2(bid, entry.get("code", ""))
            spec.append((bid, name))
            self.user_bot_ids.add(bid)

        target = max(len(spec), min(8, bot_count))   # 유저봇 수 이상, 최대 8
        rng = random.Random(seed)
        type_counts: dict[str, int] = {}
        fill_n = max(0, target - len(spec))
        for i in range(fill_n):
            label, cls = rng.choice(_AI_FILLERS)   # 랜덤 종류
            type_counts[label] = type_counts.get(label, 0) + 1
            bid = "ai_%d" % i
            name = "%s %d" % (label, type_counts[label])
            bots[bid] = cls(bid, seed=seed + 100 + i)
            spec.append((bid, name))
        return bots, spec

    async def send_match_start(self) -> None:
        self.started = True
        self._db_on_start()
        await self.send({"type": "MATCH_START"})

    # ---------- DB 기록 (games / game_participants 재활용) ----------
    def _db_on_start(self) -> None:
        """매치 시작 시: 이미 생성된 game row 재사용 + participants 등록 + running 표시.
        owner 없는 game 을 새로 만들지 않는다(생성은 인증된 POST /api/games 에서만).
        참가자가 이미 등록돼 있으면(재접속/중복 MATCH_START) 다시 넣지 않는다."""
        repo = _get_game_repo()
        if repo is None:
            return
        try:
            game = repo.get_game(self.match_id)
            if game is None:
                # 인증 경로로 생성되지 않은 매치 (예: /godot-test?match=dev). 기록 생략.
                logger.info("[match=%s] DB game 없음 — 기록 생략(비인증 데모)", self.match_id)
                return
            existing = repo.get_participants(self.match_id)
            if not existing:
                for bid, name in self.bot_spec:
                    repo.add_participant(
                        self.match_id, bot_name=name,
                        is_ai_filler=(bid not in self.user_bot_ids))
            repo.update_game_started(self.match_id)
        except Exception:  # noqa: BLE001
            logger.exception("[match=%s] _db_on_start 실패", self.match_id)
            _safe_rollback(repo)

    def _db_on_end(self, data: dict[str, Any]) -> None:
        """매치 종료 시: games finished + 참가자 결과 갱신. 이미 finished 면 스킵(중복 방지)."""
        repo = _get_game_repo()
        if repo is None:
            return
        rankings = data.get("rankings", []) if isinstance(data, dict) else []
        duration = float(data.get("duration", 0.0)) if isinstance(data, dict) else 0.0
        reason = str(data.get("reason", "max_ticks")) if isinstance(data, dict) else "max_ticks"
        try:
            game = repo.get_game(self.match_id)
            if game is None:
                return
            if getattr(game, "status", None) == "finished":
                logger.info("[match=%s] 이미 finished — MATCH_END 중복 무시", self.match_id)
                return
            repo.update_game_finished(
                game_id=self.match_id,
                final_tick=int(duration * 10.0),
                end_reason=reason,
            )
            for entry in rankings:
                name = entry.get("bot_name") or entry.get("name")
                if not name:
                    continue
                repo.update_participant_result(
                    game_id=self.match_id,
                    bot_name=name,
                    final_rank=int(entry.get("rank", 0)),
                    final_score=float(entry.get("score", 0.0)),
                    kills=int(entry.get("kills", 0)),
                    minerals_mined=int(entry.get("minerals_mined", 0)),
                    survival_ticks=int(entry.get("survival_ticks", 0)),
                )
        except Exception:  # noqa: BLE001
            logger.exception("[match=%s] _db_on_end 실패", self.match_id)
            _safe_rollback(repo)

    def handle_state(self, tick: int, data: dict[str, Any]) -> dict[str, Any]:
        """봇들의 state 를 받아 각 봇의 get_action 호출 → action dict 반환."""
        bots_state: dict[str, Any] = data.get("bots", {}) if isinstance(data, dict) else {}
        actions: dict[str, Any] = {}
        for bot_id, bot in self.bots.items():
            state = bots_state.get(bot_id)
            if state is None:
                # 시야 누락 또는 사망 처리. STAY 강제.
                actions[bot_id] = _validate_action(None)
                continue
            try:
                raw = bot.get_action(state)
            except Exception:  # noqa: BLE001 — 봇 예외는 STAY 로 폴백
                logger.exception("[match=%s tick=%d] bot=%s get_action 실패", self.match_id, tick, bot_id)
                raw = None
            actions[bot_id] = _validate_action(raw)
        return actions

    def handle_choose_spawn(self, data: dict[str, Any]) -> dict[str, list[float] | None]:
        """클라이언트가 MATCH_CONFIG 응답으로 봇별 스폰 위치 요청 시 호출용 헬퍼.

        v0.1 에서는 MATCH_CONFIG 직후 클라이언트가 'SPAWN_REQUEST' 같은 추가 메시지를
        보내면 봇들에게 choose_spawn 을 위임할 수 있음. 현재는 호출 시점에 매치 정보를 받아
        결과를 반환만 한다.
        """
        self.match_info = data
        result: dict[str, list[float] | None] = {}
        for bot_id, bot in self.bots.items():
            try:
                pos = bot.choose_spawn(data)
            except Exception:
                logger.exception("choose_spawn 실패: %s", bot_id)
                pos = None
            result[bot_id] = list(pos) if pos is not None else None
        return result

    def handle_match_end(self, data: dict[str, Any]) -> None:
        self.ended = True
        self._db_on_end(data)
        rankings = data.get("rankings", []) if isinstance(data, dict) else []
        n = len(rankings)
        for entry in rankings:
            bot_id = entry.get("bot_id")
            bot = self.bots.get(bot_id) if bot_id else None
            if bot is None:
                continue
            try:
                bot.on_episode_done(
                    rank=int(entry.get("rank", n)),
                    n_bots=n,
                    score=float(entry.get("score", 0.0)),
                )
            except Exception:
                logger.exception("on_episode_done 실패: %s", bot_id)


def create_app() -> FastAPI:
    app = FastAPI(title="BattleRoyale2 WS Server")

    # 마운트된 서브앱은 자체 미들웨어 스택을 가지므로 CORS 를 여기서 직접 추가.
    # CORS_ORIGINS 환경변수(콤마구분) 사용, 없으면 전체 허용. 쿠키 미사용이라 credentials=False.
    _cors_raw = os.environ.get("CORS_ORIGINS", "")
    origins = [o.strip() for o in _cors_raw.split(",") if o.strip()] if _cors_raw else ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:  # noqa: D401 — 짧은 헬스체크 응답
        return {"status": "ok", "protocol": PROTOCOL_VERSION}

    @app.post("/api/games", status_code=201)
    def create_game(request: Request, body: dict[str, Any] = Body(default={})):  # noqa: B008
        """새 BR2 게임 생성 → game_id 발급. 인증 필수, owner 는 토큰으로 결정.
        프론트: POST /battleroyale2/api/games → game_id → /games/{id}/battleroyale/watch.
        유저 코드/봇수는 games.config_json 에 영속(다중 인스턴스 대응).
        DB 불가 시 503 (fail-open 하지 않음)."""
        # 1) 인증 — 토큰으로 owner 결정 (body.owner_user_id 는 무시)
        owner_id = _resolve_owner_id(_bearer(request))
        if owner_id is None:
            raise HTTPException(401, "인증이 필요합니다.")

        # 2) DB 필수 — 없으면 503 (게임 생성을 성공처럼 통과시키지 않음)
        repo = _get_game_repo()
        if repo is None:
            raise HTTPException(503, "BattleRoyale2 DB를 사용할 수 없습니다.")

        # 3) 유저 봇 코드 파싱. body.bots: [{bot_id, code, name?}]
        raw_bots = body.get("bots") if isinstance(body, dict) else None
        user_bots: list[dict] = []
        if isinstance(raw_bots, list):
            for i, b in enumerate(raw_bots):
                if not isinstance(b, dict) or not b.get("code"):
                    continue
                code = str(b["code"])
                if len(code.encode("utf-8")) > 50 * 1024:
                    raise HTTPException(400, "코드가 너무 큽니다 (최대 50KB).")
                bid = str(b.get("bot_id") or ("user_%d" % i))
                user_bots.append({"bot_id": bid, "name": str(b.get("name") or bid), "code": code})

        # 4) 봇 수 (2~8, 유저봇 수 이상)
        req_count = body.get("bot_count") if isinstance(body, dict) else None
        try:
            bot_count = int(req_count) if req_count is not None else TARGET_BOT_COUNT
        except (TypeError, ValueError):
            bot_count = TARGET_BOT_COUNT
        bot_count = max(max(2, len(user_bots)), min(8, bot_count))

        # 5) 게임 생성 (owner=토큰 사용자, config_json 에 스펙 영속)
        game_id = uuid.uuid4().hex
        try:
            repo.create_game(
                game_id=game_id,
                owner_user_id=owner_id,
                total_bots=bot_count if user_bots else len(DEFAULT_BOT_FACTORY),
                seed=body.get("seed"),
                config_json=_spec_config_json(user_bots, bot_count),
                mode=GAME_MODE,
                name=(body.get("name") or None),
            )
        except Exception:  # noqa: BLE001
            logger.exception("[BR2] create_game 실패")
            _safe_rollback(repo)
            raise HTTPException(500, "게임 생성에 실패했습니다.")

        # 인메모리 캐시(동일 인스턴스 빠른 경로). 다른 인스턴스는 config_json 으로 복원.
        if user_bots:
            _GAME_CODE[game_id] = user_bots
            _GAME_BOT_COUNT[game_id] = bot_count

        # 서버사이드 헤드리스 러너 spawn (C2). 비활성(기본)이면 mgr=None → 동작 불변.
        running = False
        mgr = get_runner_manager()
        if mgr is not None:
            # 러너 비정상 종료 시 DB 정리 콜백 배선 (멱등 — 최초 1회만 설정).
            if mgr.on_exit is None:
                mgr.on_exit = _on_runner_exit
            running = mgr.try_spawn(game_id)
            if not running:
                logger.warning("[BR2] 러너 동시성 초과 — match=%s 는 대기/미시작", game_id)
        return {"game_id": game_id, "persisted": True, "running": running}

    @app.get("/api/games")
    def list_games(request: Request, limit: int = 50):
        """내 BR2 게임 목록 (owner scoped). 토큰 필수."""
        owner_id = _resolve_owner_id(_bearer(request))
        if owner_id is None:
            raise HTTPException(401, "인증이 필요합니다.")
        repo = _get_game_repo()
        if repo is None:
            raise HTTPException(503, "BattleRoyale2 DB를 사용할 수 없습니다.")
        out = []
        for g in repo.list_games_by_owner(owner_id, limit=limit):
            if getattr(g, "mode", None) != GAME_MODE:
                continue
            out.append({
                "game_id": g.id,
                "name": g.name,
                "mode": GAME_MODE,
                "status": g.status,
                "total_bots": g.total_bots,
                "created_at": getattr(g, "created_at", None),
                "started_at": g.started_at,
                "finished_at": g.finished_at,
                "end_reason": g.end_reason,
            })
        return out

    @app.get("/api/games/{game_id}/result")
    def get_result(game_id: str, request: Request):
        """매치 결과 상세 (순위/점수/킬/생존). 토큰 필수. 종료 전이면 status 만 반환."""
        owner_id = _resolve_owner_id(_bearer(request))
        if owner_id is None:
            raise HTTPException(401, "인증이 필요합니다.")
        repo = _get_game_repo()
        if repo is None:
            raise HTTPException(503, "BattleRoyale2 DB를 사용할 수 없습니다.")
        g = repo.get_game(game_id)
        if g is None or getattr(g, "mode", None) != GAME_MODE:
            raise HTTPException(404, "게임을 찾을 수 없습니다.")
        rankings = []
        for p in repo.get_participants(game_id):
            rankings.append({
                "rank": p.final_rank,
                "bot_name": p.bot_name,
                "is_ai_filler": p.is_ai_filler,
                "score": p.final_score,
                "kills": p.kills,
                "minerals_mined": p.minerals_mined,
                "survival_ticks": p.survival_ticks,
            })
        rankings.sort(key=lambda r: (r["rank"] is None, r["rank"] if r["rank"] is not None else 0))
        return {
            "game_id": g.id,
            "name": g.name,
            "status": g.status,
            "end_reason": g.end_reason,
            "finished_at": g.finished_at,
            "final_tick": g.final_tick,
            "rankings": rankings,
        }

    @app.get("/api/games/{game_id}/replay")
    async def get_replay(game_id: str):
        """기록된 프레임(FRAME_INIT + FRAME 누적) 반환. 리플레이/라이브 따라보기 공용."""
        store = await _get_state_store()
        if store is None:
            return {"game_id": game_id, "total_frames": 0, "frames": []}
        frames = await store.get_replay_frames(game_id)
        return {"game_id": game_id, "total_frames": len(frames), "frames": frames}

    # 통합 서버에 /battleroyale2 로 mount 되므로 여기선 prefix 없이 /match/{id}.
    # 최종 경로: ws://<host>/battleroyale2/match/{match_id}
    # (단독 실행 시 BattleRoyale2.run_server 도 동일 앱을 그대로 띄움)
    @app.websocket("/match/{match_id}")
    async def match_ws(ws: WebSocket, match_id: str) -> None:
        # 인증: 실제 DB 게임(인증된 POST 로 생성)이면 ?token= 검증 필수.
        # DB game 이 없는 데모 매치(예: dev)는 토큰 없이 허용(로컬 개발).
        repo = _get_game_repo()
        game = None
        if repo is not None:
            try:
                game = repo.get_game(match_id)
            except Exception:  # noqa: BLE001
                game = None
        token = ws.query_params.get("token")
        if game is not None:
            # 서버 헤드리스 러너(C2)는 공유 시크릿 토큰으로 인증 — Firebase 토큰 아님.
            valid = _is_runner_token(token) or (bool(token) and _decode_token(token) is not None)
            if not valid:
                # 토큰 없음/무효 → 거부 (누구나 관전 가능하나 인증은 필요)
                await ws.close(code=4401)
                logger.info("[match=%s] WS 인증 실패 — 거부", match_id)
                return

        await ws.accept()
        session = MatchSession(ws, match_id)
        # 권위(시뮬·기록) 결정. 서버 러너가 도는 매치는 접속 순서가 아니라 "러너 토큰" 으로 권위를 정한다
        # → 브라우저가 러너보다 먼저 붙어도 관전자가 됨(race 방지). 그 외(데모/로컬)는 첫 연결이 권위.
        _mgr = get_runner_manager()
        server_run = _mgr is not None and _mgr.is_active(match_id)
        eligible = _is_runner_token(token) if server_run else True
        if eligible and match_id not in _AUTHORITATIVE:
            _AUTHORITATIVE[match_id] = id(session)
            session.authoritative = True
        logger.info("[match=%s] WS connected (authoritative=%s, server_run=%s)",
                    match_id, session.authoritative, server_run)

        try:
            while True:
                frame = await ws.receive()
                # 연결 종료 프레임 처리
                if frame.get("type") == "websocket.disconnect":
                    break
                # text / bytes 둘 다 수용 (Godot WebSocketClient 는 기본 binary)
                raw = frame.get("text")
                if raw is None:
                    raw_bytes = frame.get("bytes")
                    if raw_bytes is None:
                        continue
                    try:
                        raw = raw_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        logger.warning("non-utf8 bytes frame received, skipping")
                        continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("invalid JSON: %s", raw[:200])
                    continue
                if not isinstance(msg, dict) or "type" not in msg:
                    continue

                mtype = msg["type"]
                tick = msg.get("tick", 0)
                data = msg.get("data", {})

                if mtype == "HELLO":
                    client_version = data.get("version") if isinstance(data, dict) else None
                    if client_version != PROTOCOL_VERSION:
                        await session.send({
                            "type": "ERROR",
                            "data": {"code": "VERSION_MISMATCH",
                                     "message": f"server={PROTOCOL_VERSION} client={client_version}"},
                        })
                        await ws.close()
                        return
                    if session.authoritative:
                        # 권위(러너): 자동으로 MATCH_CONFIG → MATCH_START 진행 (v0.1 단순화)
                        await session.send({"type": "ROLE", "data": {"role": "runner"}})
                        await session.send_match_config(seed=int(data.get("seed", 0)) if isinstance(data, dict) else 0)
                        await session.send_match_start()
                    else:
                        # 관전자: 시뮬 안 함. 역할 통보 후 누적 프레임 catch-up + 이후 live tail 중계.
                        await session.send({"type": "ROLE", "data": {"role": "spectator"}})
                        _SPECTATORS.setdefault(match_id, set()).add(session)
                        await _pump_spectator(match_id, session)

                elif mtype == "MATCH_INFO":
                    # 클라이언트가 매치 정보(클러스터/Zone1 등) 를 보내면 spawn 추첨 응답
                    spawn_choices = session.handle_choose_spawn(data if isinstance(data, dict) else {})
                    await session.send({
                        "type": "SPAWN_CHOICES",
                        "data": {"spawns": spawn_choices},
                    })

                elif mtype == "STATE":
                    if not session.started:
                        continue
                    actions = session.handle_state(tick, data if isinstance(data, dict) else {})
                    await session.send({
                        "type": "ACTIONS",
                        "tick": tick,
                        "data": actions,
                    })

                elif mtype == "EVENT":
                    # 로그만 출력. 추후 DB 적재로 확장.
                    ev = data if isinstance(data, dict) else {}
                    logger.info("[match=%s tick=%d] EVENT %s actor=%s target=%s",
                                match_id, tick, ev.get("event"), ev.get("actor_id"), ev.get("target_id"))

                elif mtype == "FRAME_INIT":
                    # 정적 월드 스냅샷. 권위 세션만 기록 → 관전자 중계.
                    if session.authoritative:
                        store = await _get_state_store()
                        if store is not None:
                            await store.append_replay_frame(
                                match_id, {"kind": "init", "data": data if isinstance(data, dict) else {}})
                            await _broadcast_frame(match_id)

                elif mtype == "FRAME":
                    # 매 틱 동적 상태 + 델타. 권위 세션만 기록 → 관전자 중계.
                    if session.authoritative:
                        store = await _get_state_store()
                        if store is not None:
                            await store.append_replay_frame(
                                match_id, {"kind": "frame", "tick": tick,
                                           "data": data if isinstance(data, dict) else {}})
                            await _broadcast_frame(match_id)

                elif mtype == "MATCH_END":
                    session.handle_match_end(data if isinstance(data, dict) else {})
                    # 관전자에게 매치 종료 + 결과 중계 (관전 화면에 결과창 표시용)
                    specs = _SPECTATORS.get(match_id)
                    if specs:
                        end_msg = {"type": "MATCH_END", "data": data if isinstance(data, dict) else {}}
                        for s in list(specs):
                            try:
                                await s.send(end_msg)
                            except Exception:  # noqa: BLE001
                                specs.discard(s)
                    logger.info("[match=%s] MATCH_END received", match_id)
                    break

                else:
                    logger.warning("[match=%s] unknown message type: %s", match_id, mtype)

        except WebSocketDisconnect:
            logger.info("[match=%s] WS disconnected", match_id)
        except Exception:  # noqa: BLE001
            logger.exception("[match=%s] unexpected error", match_id)
        finally:
            # 권위 세션이 끊기면 레지스트리에서 해제 (다음 연결이 권위 승계 가능)
            if session.authoritative and _AUTHORITATIVE.get(match_id) == id(session):
                _AUTHORITATIVE.pop(match_id, None)
            # 관전 세션 정리
            specs = _SPECTATORS.get(match_id)
            if specs is not None:
                specs.discard(session)
                if not specs:
                    _SPECTATORS.pop(match_id, None)
            try:
                await ws.close()
            except Exception:
                pass

    return app


app = create_app()
