"""
AI Arena — 봇 인터페이스
모든 봇(로컬, 콜드스타트, 추후 Docker)이 구현하는 공통 인터페이스.

Phase 2에서 DockerBotAdapter로 교체할 때 이 인터페이스만 맞추면 된다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BotInterface(ABC):
    """봇이 구현해야 하는 최소 인터페이스."""

    @abstractmethod
    def get_action(self, state: dict) -> str:
        """
        서버가 전달한 state를 받아 11가지 행동 코드 중 하나를 반환.

        Args:
            state: 현재 틱의 게임 상태 딕셔너리
                   (tick, my_bot, vision, zone_boundary, leaderboard)

        Returns:
            행동 문자열: "STAY" | "MOVE_UP" | "MOVE_DOWN" | "MOVE_LEFT" |
                        "MOVE_RIGHT" | "MINE" | "ATTACK_UP" | "ATTACK_DOWN" |
                        "ATTACK_LEFT" | "ATTACK_RIGHT" | "SHIELD"

        Raises:
            어떤 예외가 발생하든 엔진이 잡아서 STAY로 처리한다.
        """
        ...

    @property
    @abstractmethod
    def bot_id(self) -> str:
        """이 봇의 고유 식별자."""
        ...
