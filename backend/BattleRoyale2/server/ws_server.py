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

import json
import logging
import os
import random
import time
import uuid
from typing import Any

from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from BattleRoyale2.bots import HerbivoreBot, MadDogBot, CamperBot
from BattleRoyale2.server.inprocess_bot import InProcessBot2
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

# match_id → 권위 세션의 id(). 첫 WS 연결이 권위. (PROTOCOL.md §3.13)
_AUTHORITATIVE: dict[str, int] = {}


def _get_state_store():
    global _STATE_STORE, _STATE_STORE_TRIED
    if _STATE_STORE_TRIED:
        return _STATE_STORE
    _STATE_STORE_TRIED = True
    try:
        from src.arena.server.redis_manager import InMemoryStateStore  # type: ignore
        _STATE_STORE = InMemoryStateStore()
        logger.info("[BR2] InMemoryStateStore 사용 (프레임 기록 활성)")
    except Exception as e:  # noqa: BLE001
        logger.warning("[BR2] StateStore 로드 실패 — 프레임 기록 비활성 (%s)", e)
        _STATE_STORE = None
    return _STATE_STORE

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
        AI 채움은 초식/미친개/존버 중 랜덤 선택, 총 봇 수는 _GAME_BOT_COUNT 기준."""
        user_bots = _GAME_CODE.get(self.match_id, [])
        if not user_bots:
            bots = _build_bots(list(DEFAULT_BOT_FACTORY), seed=seed)
            return bots, list(DEFAULT_BOT_FACTORY)

        bots: dict[str, BattleRoyale2DBot] = {}
        spec: list[tuple[str, str]] = []
        for entry in user_bots:
            bid = entry["bot_id"]
            name = entry.get("name", bid)
            bots[bid] = InProcessBot2(bid, entry.get("code", ""))
            spec.append((bid, name))

        target = _GAME_BOT_COUNT.get(self.match_id, TARGET_BOT_COUNT)
        target = max(len(spec), min(8, target))   # 유저봇 수 이상, 최대 8
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
        """매치 시작 시: games 행 생성(없으면) + participants 추가 + running 표시."""
        repo = _get_game_repo()
        if repo is None:
            return
        try:
            game = repo.get_game(self.match_id)
            if game is None:
                repo.create_game(
                    game_id=self.match_id,
                    owner_user_id=None,
                    total_bots=len(self.bot_spec),
                    seed=None,
                    mode=GAME_MODE,
                    name=None,
                )
            # 참가자 등록 (AI 봇)
            for _bid, name in self.bot_spec:
                repo.add_participant(self.match_id, bot_name=name, is_ai_filler=True)
            repo.update_game_started(self.match_id)
        except Exception:  # noqa: BLE001
            logger.exception("[match=%s] _db_on_start 실패", self.match_id)

    def _db_on_end(self, data: dict[str, Any]) -> None:
        """매치 종료 시: games finished + 참가자 결과 갱신."""
        repo = _get_game_repo()
        if repo is None:
            return
        rankings = data.get("rankings", []) if isinstance(data, dict) else []
        duration = float(data.get("duration", 0.0)) if isinstance(data, dict) else 0.0
        reason = str(data.get("reason", "max_ticks")) if isinstance(data, dict) else "max_ticks"
        try:
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

    @app.post("/api/games")
    def create_game(body: dict[str, Any] = Body(default={})):  # noqa: B008
        """새 BR2 게임 레코드 생성 → game_id 발급.
        프론트: POST /battleroyale2/api/games → game_id → /games/{id}/watch (Godot match={id}).
        실제 매치 진행/참가자 등록은 WS MATCH_START 시점에 보강된다.
        """
        game_id = uuid.uuid4().hex

        # 유저 봇 코드 저장 (인메모리). body.bots: [{bot_id, code, name?, is_public?}]
        raw_bots = body.get("bots") if isinstance(body, dict) else None
        user_bots: list[dict] = []
        if isinstance(raw_bots, list):
            for i, b in enumerate(raw_bots):
                if not isinstance(b, dict) or not b.get("code"):
                    continue
                bid = str(b.get("bot_id") or ("user_%d" % i))
                user_bots.append({
                    "bot_id": bid,
                    "name": str(b.get("name") or bid),
                    "code": str(b["code"]),
                })
        if user_bots:
            _GAME_CODE[game_id] = user_bots

        # 봇 수 (내 봇 + AI 채움). 2~8 클램프. 유저봇 수보다는 커야 함.
        req_count = body.get("bot_count") if isinstance(body, dict) else None
        try:
            bot_count = int(req_count) if req_count is not None else TARGET_BOT_COUNT
        except (TypeError, ValueError):
            bot_count = TARGET_BOT_COUNT
        bot_count = max(max(2, len(user_bots)), min(8, bot_count))
        if user_bots:
            _GAME_BOT_COUNT[game_id] = bot_count

        total_bots = bot_count if user_bots else len(DEFAULT_BOT_FACTORY)

        repo = _get_game_repo()
        if repo is None:
            # DB 비활성 환경에서도 game_id 는 발급 (저장만 생략)
            return {"game_id": game_id, "persisted": False}
        try:
            repo.create_game(
                game_id=game_id,
                owner_user_id=body.get("owner_user_id"),
                total_bots=total_bots,
                seed=body.get("seed"),
                mode=GAME_MODE,
                name=body.get("name"),
            )
            return {"game_id": game_id, "persisted": True}
        except Exception:  # noqa: BLE001
            logger.exception("[BR2] create_game 실패")
            return {"game_id": game_id, "persisted": False}

    @app.get("/api/games/{game_id}/replay")
    async def get_replay(game_id: str):
        """기록된 프레임(FRAME_INIT + FRAME 누적) 반환. 리플레이/라이브 따라보기 공용."""
        store = _get_state_store()
        if store is None:
            return {"game_id": game_id, "total_frames": 0, "frames": []}
        frames = await store.get_replay_frames(game_id)
        return {"game_id": game_id, "total_frames": len(frames), "frames": frames}

    # 통합 서버에 /battleroyale2 로 mount 되므로 여기선 prefix 없이 /match/{id}.
    # 최종 경로: ws://<host>/battleroyale2/match/{match_id}
    # (단독 실행 시 BattleRoyale2.run_server 도 동일 앱을 그대로 띄움)
    @app.websocket("/match/{match_id}")
    async def match_ws(ws: WebSocket, match_id: str) -> None:
        await ws.accept()
        session = MatchSession(ws, match_id)
        # 첫 연결이 권위 (시뮬·기록 담당). 이후 연결은 관전 역할 → FRAME 무시.
        if match_id not in _AUTHORITATIVE:
            _AUTHORITATIVE[match_id] = id(session)
            session.authoritative = True
        logger.info("[match=%s] WS connected (authoritative=%s)", match_id, session.authoritative)

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
                    # 자동으로 MATCH_CONFIG → MATCH_START 진행 (v0.1 단순화)
                    await session.send_match_config(seed=int(data.get("seed", 0)) if isinstance(data, dict) else 0)
                    await session.send_match_start()

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
                    # 정적 월드 스냅샷. 권위 세션만 기록.
                    if session.authoritative:
                        store = _get_state_store()
                        if store is not None:
                            await store.append_replay_frame(
                                match_id, {"kind": "init", "data": data if isinstance(data, dict) else {}})

                elif mtype == "FRAME":
                    # 매 틱 동적 상태 + 델타. 권위 세션만 기록.
                    if session.authoritative:
                        store = _get_state_store()
                        if store is not None:
                            await store.append_replay_frame(
                                match_id, {"kind": "frame", "tick": tick,
                                           "data": data if isinstance(data, dict) else {}})

                elif mtype == "MATCH_END":
                    session.handle_match_end(data if isinstance(data, dict) else {})
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
            try:
                await ws.close()
            except Exception:
                pass

    return app


app = create_app()
