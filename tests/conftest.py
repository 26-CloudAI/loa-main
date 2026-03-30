"""테스트 공통 픽스처."""

import sys
from pathlib import Path

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from src.arena.bot_interface import BotInterface
from src.arena.config import GameConfig, MapConfig, BotConfig, ZoneConfig
from src.arena.engine import GameEngine


class DummyBot(BotInterface):
    """테스트용 봇. 항상 지정된 액션을 반환."""

    def __init__(self, bot_id: str, action: str = "STAY"):
        self._bot_id = bot_id
        self._action = action
        self.action_history: list[dict] = []

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def get_action(self, state: dict) -> str:
        self.action_history.append(state)
        return self._action

    def set_action(self, action: str) -> None:
        self._action = action


class ScriptedBot(BotInterface):
    """테스트용 봇. 틱별로 미리 정해진 액션을 순서대로 반환."""

    def __init__(self, bot_id: str, actions: list[str]):
        self._bot_id = bot_id
        self._actions = actions
        self._tick = 0

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def get_action(self, state: dict) -> str:
        if self._tick < len(self._actions):
            action = self._actions[self._tick]
        else:
            action = "STAY"
        self._tick += 1
        return action


def make_small_config(**overrides) -> GameConfig:
    """테스트용 소규모 설정. 기본 10×10 맵, 광물 10개."""
    map_cfg = overrides.pop("map", MapConfig(
        width=10, height=10,
        initial_mineral_count=10,
        center_zone_size=4,
        rare_zone_size=3,
    ))
    bot_cfg = overrides.pop("bot", BotConfig(
        initial_energy=100,
        max_bots=10,
        spawn_margin=3,
        vision_radius=2,
    ))
    zone_cfg = overrides.pop("zone", ZoneConfig(
        phase1_end=50,
        phase2_end=80,
        phase2_shrink_interval=10,
        phase2_damage=3,
        phase3_shrink_interval=5,
        phase3_damage=3,
    ))
    return GameConfig(
        max_ticks=100,
        map=map_cfg,
        bot=bot_cfg,
        zone=zone_cfg,
        **overrides,
    )


@pytest.fixture
def small_config():
    return make_small_config()
