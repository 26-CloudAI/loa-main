"""
AI Arena — 자기장(Zone) 시스템
시간이 지날수록 맵 외곽부터 위험 영역이 수축하여 봇을 중앙으로 유도한다.

수축 스케줄:
  0 ~ 299틱  : 자기장 없음 (자유 탐색)
  300 ~ 449틱: 20틱마다 경계 1칸 수축, 영역 밖 -3 에너지/틱
  450 ~ 500틱: 10틱마다 경계 1칸 수축 (가속), -3 에너지/틱
"""

from __future__ import annotations

from .config import GameConfig
from .types import Position


class ZoneManager:
    """
    자기장 경계를 관리한다.
    boundary는 맵 가장자리에서 안쪽으로의 칸 수.
    boundary=0이면 자기장 없음, boundary=10이면 가장자리 10칸이 위험 영역.
    """

    def __init__(self, config: GameConfig):
        self.config = config
        self.zc = config.zone
        self.boundary: int = 0

    def update(self, tick: int) -> None:
        """현재 틱에 맞춰 자기장 경계를 업데이트한다."""
        if tick <= self.zc.phase1_end:
            # Phase 1: 자기장 없음
            return

        if tick <= self.zc.phase2_end:
            # Phase 2: 20틱마다 수축
            ticks_into_phase = tick - self.zc.phase1_end
            self.boundary = ticks_into_phase // self.zc.phase2_shrink_interval
        else:
            # Phase 3: 가속 수축
            phase2_shrinks = (
                (self.zc.phase2_end - self.zc.phase1_end)
                // self.zc.phase2_shrink_interval
            )
            ticks_into_phase3 = tick - self.zc.phase2_end
            phase3_shrinks = ticks_into_phase3 // self.zc.phase3_shrink_interval
            self.boundary = phase2_shrinks + phase3_shrinks

    def is_outside_safe_zone(self, pos: Position) -> bool:
        """해당 위치가 자기장 영역(위험 구역) 안에 있는지 확인."""
        if self.boundary <= 0:
            return False

        w = self.config.map.width
        h = self.config.map.height

        return (
            pos.x < self.boundary
            or pos.x >= w - self.boundary
            or pos.y < self.boundary
            or pos.y >= h - self.boundary
        )

    def get_zone_damage(self, tick: int) -> int:
        """현재 틱의 자기장 데미지를 반환."""
        if tick <= self.zc.phase1_end:
            return 0
        if tick <= self.zc.phase2_end:
            return self.zc.phase2_damage
        return self.zc.phase3_damage

    def get_safe_bounds(self) -> tuple[int, int, int, int]:
        """안전 영역의 (min_x, min_y, max_x, max_y) 반환."""
        w = self.config.map.width
        h = self.config.map.height
        b = self.boundary
        return (b, b, w - b - 1, h - b - 1)
