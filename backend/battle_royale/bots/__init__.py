"""AI Arena — 봇 패키지.

서브패키지:
  - bots.battle_royale: 배틀로얄 콜드스타트/샘플 봇
  - bots.boss: 보스전 전용 봇 (룰/RL)
  - bots.utils: 공통 유틸 (좌표 상수, 이동 헬퍼)
"""

from .battle_royale import CamperBot, HerbivoreBot, MadDogBot

__all__ = ["HerbivoreBot", "MadDogBot", "CamperBot"]
