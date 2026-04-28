"""
AI Arena — 봇 인터페이스
모든 봇(로컬, 콜드스타트, 추후 Docker)이 구현하는 공통 인터페이스.

Phase 2에서 DockerBotAdapter로 교체할 때 이 인터페이스만 맞추면 된다.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from abc import ABC, abstractmethod

if TYPE_CHECKING:
    from .grid import Grid


class BotInterface(ABC):
    """봇이 구현해야 하는 최소 인터페이스."""

    def choose_spawn(self, map_info: dict) -> tuple[int, int] | None:  # noqa: ARG002
        """
        게임 시작 전 맵 정보를 보고 원하는 스폰 위치를 반환한다.

        Args:
            map_info: 초기 맵 정보 딕셔너리
                {
                    "width":    int,
                    "height":   int,
                    "minerals": [{"x": int, "y": int, "rare": bool}, ...]
                }

        Returns:
            (x, y) 좌표 튜플. None 반환 시 랜덤 스폰.
            같은 칸을 요청한 봇이 여럿이면 엔진이 무작위로 1명만 허용하고
            나머지는 랜덤 스폰으로 처리한다.

        Raises:
            어떤 예외가 발생하든 엔진이 잡아서 랜덤 스폰으로 처리한다.
        """
        return None

    def on_episode_done(self, rank: int, n_bots: int) -> None:
        """
        게임 종료 시 엔진이 호출하는 훅. 기본 구현은 아무것도 하지 않음.
        학습 봇은 이 메서드를 오버라이드해 종료 보상 처리와 가중치 저장을 수행한다.

        Args:
            rank:   이번 게임 최종 순위 (1이 1등)
            n_bots: 이번 게임 총 봇 수
        """

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
