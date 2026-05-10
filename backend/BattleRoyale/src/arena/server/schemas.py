"""
AI Arena — API 스키마
REST API 및 WebSocket 메시지의 데이터 구조 정의.

Pydantic이 없는 환경에서도 import 가능하도록
dict 기반 팩토리 함수를 병행 제공.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


# ──────────────────────────────────────────────
#  게임 상태 enum
# ──────────────────────────────────────────────

class GameStatus(str, Enum):
    WAITING = "waiting"         # 봇 등록 대기 중
    RUNNING = "running"         # 게임 진행 중
    FINISHED = "finished"       # 게임 종료
    ERROR = "error"             # 오류로 중단


# ──────────────────────────────────────────────
#  REST API 스키마
# ──────────────────────────────────────────────

@dataclass
class BotSubmission:
    """봇 코드 업로드 요청."""
    bot_id: str
    code: str


@dataclass
class CreateGameRequest:
    """게임 생성 요청."""
    bots: list[BotSubmission]
    tick_interval: float = 0.05         # 관전 속도
    use_sandbox: bool = False           # Docker 샌드박스 사용 여부
    seed: Optional[int] = None
    fill_with_ai: bool = True           # 빈자리 AI 봇으로 채우기
    min_bots: int = 4                   # 최소 봇 수

    def to_dict(self) -> dict:
        return {
            "bots": [{"bot_id": b.bot_id, "code": b.code} for b in self.bots],
            "tick_interval": self.tick_interval,
            "use_sandbox": self.use_sandbox,
            "seed": self.seed,
            "fill_with_ai": self.fill_with_ai,
            "min_bots": self.min_bots,
        }


@dataclass
class GameInfo:
    """게임 정보 응답."""
    game_id: str
    status: GameStatus
    current_tick: int = 0
    total_bots: int = 0
    alive_bots: int = 0
    bot_ids: list[str] = field(default_factory=list)
    name: Optional[str] = None
    mode: str = "battle-royale"
    created_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "status": self.status.value,
            "current_tick": self.current_tick,
            "total_bots": self.total_bots,
            "alive_bots": self.alive_bots,
            "bot_ids": self.bot_ids,
            "name": self.name,
            "mode": self.mode,
            "created_at": self.created_at,
        }


@dataclass
class GameResultResponse:
    """게임 결과 응답."""
    game_id: str
    reason: str
    final_tick: int
    rankings: list[dict]

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "reason": self.reason,
            "final_tick": self.final_tick,
            "rankings": self.rankings,
        }


# ──────────────────────────────────────────────
#  WebSocket 메시지 스키마
# ──────────────────────────────────────────────

class WSMessageType(str, Enum):
    """WebSocket 메시지 타입."""
    TICK = "tick"               # 틱 상태 업데이트
    EVENT = "event"             # 킬, 채굴 등 이벤트
    GAME_START = "game_start"   # 게임 시작
    GAME_END = "game_end"       # 게임 종료
    ERROR = "error"             # 오류
    PING = "ping"
    PONG = "pong"


@dataclass
class TickBroadcast:
    """
    매 틱마다 모든 관전 클라이언트에게 전송하는 전체 상태.
    프론트엔드가 이 데이터만으로 화면을 완전히 렌더링할 수 있어야 한다.
    """
    tick: int
    bots: list[dict]            # [{id, x, y, energy, score, alive, shield_active}, ...]
    minerals: list[dict]        # [{x, y, rare}, ...] (채굴 가능한 것만)
    zone_bounds: list[int]      # 비대칭 자기장 경계 [minX, minY, maxX, maxY]
    alive_count: int
    leaderboard: list[dict]     # [{rank, id, score}, ...]

    def to_dict(self) -> dict:
        return {
            "type": WSMessageType.TICK.value,
            "data": {
                "tick": self.tick,
                "bots": self.bots,
                "minerals": self.minerals,
                "zone_bounds": self.zone_bounds,
                "alive_count": self.alive_count,
                "leaderboard": self.leaderboard,
            },
        }


@dataclass
class EventBroadcast:
    """개별 이벤트 브로드캐스트."""
    tick: int
    event_type: str
    actor_id: Optional[str] = None
    target_id: Optional[str] = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "type": WSMessageType.EVENT.value,
            "data": {
                "tick": self.tick,
                "event_type": self.event_type,
                "actor_id": self.actor_id,
                "target_id": self.target_id,
                "detail": self.detail,
            },
        }


def make_game_start_message(game_id: str, bot_ids: list[str]) -> dict:
    return {
        "type": WSMessageType.GAME_START.value,
        "data": {
            "game_id": game_id,
            "bot_ids": bot_ids,
        },
    }


def make_game_end_message(game_id: str, reason: str, rankings: list[dict]) -> dict:
    return {
        "type": WSMessageType.GAME_END.value,
        "data": {
            "game_id": game_id,
            "reason": reason,
            "rankings": rankings,
        },
    }


def make_error_message(error: str) -> dict:
    return {
        "type": WSMessageType.ERROR.value,
        "data": {"error": error},
    }
