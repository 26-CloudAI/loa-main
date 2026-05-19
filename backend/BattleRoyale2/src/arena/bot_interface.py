"""BattleRoyale2 — 봇 인터페이스.

연속 2D 배틀로얄에서 각 봇이 구현해야 하는 최소 인터페이스.
Godot 클라이언트와 WebSocket(PROTOCOL.md) 으로 주고받는 데이터를 처리한다.

기존 BattleRoyale.BotInterface (그리드 + 11개 action) 과는 별개 인터페이스.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BattleRoyale2DBot(ABC):
    """연속 2D 배틀로얄 봇 베이스 클래스."""

    @property
    @abstractmethod
    def bot_id(self) -> str:
        """봇 식별자."""

    def choose_spawn(self, map_info: dict[str, Any]) -> tuple[float, float] | None:
        """매치 시작 시 1회 호출. 원하는 스폰 위치를 (x, y) 로 반환.

        Args:
            map_info: 매치 정보 (GAME_RULES.md §7.3)
                {
                    "map_size":       [w, h],
                    "rare_clusters":  [[x, y], ...],
                    "chest_clusters": [[x, y], ...],
                    "zone1_center":   [x, y],
                    "zone1_radius":   float,
                }

        Returns:
            (x, y) 좌표 튜플. None 이면 엔진이 랜덤 스폰 결정.
        """
        return None

    @abstractmethod
    def get_action(self, state: dict[str, Any]) -> dict[str, Any]:
        """매 결정 틱(100ms) 호출. 행동 dict 반환.

        Args:
            state: 봇 시점의 게임 상태 (GAME_RULES.md §9.1, PROTOCOL.md §3.4)
                {
                    "time": float,
                    "self": {
                        "pos": [x, y], "vel": [x, y],
                        "hp": int, "max_hp": int,
                        "atk": int, "def": int, "speed": float,
                        "attack_cd": float, "dash_cd": float, "guard_cd": float,
                        "has_potion": bool, "has_ranged": bool,
                        "items": [str, ...],
                        "guarding": bool,
                    },
                    "vision": {
                        "enemies":     [{"id": str, "pos": [x, y], "hp": int, "guarding": bool}, ...],
                        "items":       [{"pos": [x, y], "type": str}, ...],
                        "nodes":       [{"pos": [x, y], "rare": bool}, ...],
                        "chests":      [{"pos": [x, y]}, ...],
                        "projectiles": [{"pos": [x, y], "vel": [x, y], "owner_id": str}, ...],
                    },
                    "zone": {"active": bool, "center": [x, y], "radius": float, "damage": float, "phase": int},
                    "leaderboard": [{"id": str, "score": float}, ...],
                }

        Returns:
            액션 dict (GAME_RULES.md §4, PROTOCOL.md §3.5):
                {
                    "move_dir":   [x, y],   # 정규화 벡터, 길이=속도비율(0~1)
                    "aim_dir":    [x, y],   # 조준 방향 단위 벡터
                    "attack":     bool,
                    "guard":      bool,
                    "dash":       bool,
                    "pickup":     bool,     # 상자 열기
                    "use_potion": bool,
                }
        """

    def on_episode_done(self, rank: int, n_bots: int, score: float) -> None:  # noqa: ARG002
        """매치 종료 시 1회 호출. 학습 봇이 가중치 저장 등에 활용. 기본 no-op."""


__all__ = ["BattleRoyale2DBot"]
