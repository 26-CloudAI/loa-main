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
import time
import uuid
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from BattleRoyale2.bots import HerbivoreBot
from BattleRoyale2.src.arena.bot_interface import BattleRoyale2DBot

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "0.1"
DEFAULT_BOT_FACTORY: list[tuple[str, str]] = [
    # (bot_id, display_name) — 매치 진입 시 이 목록대로 봇 인스턴스 생성
    ("bot_a", "ALPHA"),
    ("bot_b", "BRAVO"),
    ("bot_c", "CHARLIE"),
]


def _build_bots(spec: list[tuple[str, str]], seed: int | None = None) -> dict[str, BattleRoyale2DBot]:
    """현재는 모두 HerbivoreBot. 추후 봇 종류 다양화."""
    rng_seed = seed if seed is not None else 0
    return {bot_id: HerbivoreBot(bot_id, seed=rng_seed + i) for i, (bot_id, _) in enumerate(spec)}


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

    async def send(self, payload: dict[str, Any]) -> None:
        await self.ws.send_text(json.dumps(payload, separators=(",", ":")))

    async def send_match_config(self, seed: int = 0) -> None:
        self.bots = _build_bots(self.bot_spec, seed=seed)
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

    async def send_match_start(self) -> None:
        self.started = True
        await self.send({"type": "MATCH_START"})

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

    @app.get("/health")
    def health() -> dict[str, str]:  # noqa: D401 — 짧은 헬스체크 응답
        return {"status": "ok", "protocol": PROTOCOL_VERSION}

    @app.websocket("/battleroyale/match/{match_id}")
    async def match_ws(ws: WebSocket, match_id: str) -> None:
        await ws.accept()
        session = MatchSession(ws, match_id)
        logger.info("[match=%s] WS connected", match_id)

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
            try:
                await ws.close()
            except Exception:
                pass

    return app


app = create_app()
