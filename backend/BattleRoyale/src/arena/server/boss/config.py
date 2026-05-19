"""보스전 전용 게임 설정.

엔진/배틀로얄 기본값(DEFAULT_CONFIG)을 보스전에 맞게 지역 오버라이드한다.
전역 설정을 변경하지 않으므로 일반 배틀로얄에 영향 없음.
"""

from __future__ import annotations

import dataclasses

from ...config import DEFAULT_CONFIG, GameConfig

# 보스전 유저봇 최대 수 — 여기만 바꾸면 app.py·BOSS_BOT.md 모두 반영
BOSS_MAX_USER_BOTS: int = 3


def boss_battle_config() -> GameConfig:
    """
    보스전 전용 게임 설정.

    주요 변경:
      max_ticks         200 → 400  (전략 깊이 확보, 채굴 비중 상향)
      광물              300 → 400  (봇 수 증가 대비 자원 확대)
      희귀 군락          5 → 6     (추가 전략 거점)
      zone.phase1_end   75 → 150  (자유 탐색 시간 2배)
      zone.phase2_end  150 → 320  (점진 수축 구간 170틱, 8틱마다)
      zone.phase3_interval 2 → 5  (엔드게임 수축 완화)
      → 총 수축 37회, 최종 안전구역 ≈ 27×27
    """
    return dataclasses.replace(
        DEFAULT_CONFIG,
        max_ticks=400,
        map=dataclasses.replace(
            DEFAULT_CONFIG.map,
            initial_mineral_count=400,
            num_rare_mineral_clusters=6,
        ),
        zone=dataclasses.replace(
            DEFAULT_CONFIG.zone,
            phase1_end=150,
            phase2_end=320,
            phase2_shrink_interval=8,
            phase3_shrink_interval=5,
        ),
    )
