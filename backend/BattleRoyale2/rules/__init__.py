"""BattleRoyale2 게임 룰엔진 — 모드별 매치 환경 오버라이드.

여기엔 봇의 의사결정 코드가 아니라, *게임 룰 자체* (매치 길이/자원/zone 타이밍/봇 슬롯 등)
의 모드별 변형을 정의한다. ws_server 가 MATCH_CONFIG 빌드 시 참조하고, Godot 클라이언트가
적용할 contract 를 제공한다 (별도 리포 loa-battleroyale-game / PROTOCOL.md).

하위 모듈:
    boss_mode : 보스전 (보스 1 + 유저봇 최대 3 + AI 채움) — 옛 boss_battle_config() BR2 매핑.
"""

from . import boss_mode

__all__ = ["boss_mode"]
