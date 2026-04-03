"""
AI Arena — 자기장(Zone) 시스템
시간이 지날수록 맵 외곽부터 위험 영역이 수축하여 봇을 중앙으로 유도한다.

수축 스케줄:
  0 ~ 299틱  : 자기장 없음 (자유 탐색)
  300 ~ 449틱: 20틱마다 경계 1칸 수축, 영역 밖 -3 에너지/틱
  450 ~ 500틱: 10틱마다 경계 1칸 수축 (가속), -3 에너지/틱
"""

from __future__ import annotations

import random
from .config import GameConfig
from .types import Position


class ZoneManager:
    """
    자기장 경계를 관리한다.
    """

    def __init__(self, config: GameConfig, rng: random.Random | None = None):
        self.config = config
        self.zc = config.zone
        self.rng = rng or random.Random()
        self.boundary: int = 0
        
        w = self.config.map.width
        h = self.config.map.height
        self.bounds = (0, 0, w - 1, h - 1)
        self.current_shrink = 0

        # 총 수축 횟수 계산
        phase2_shrinks = (self.zc.phase2_end - self.zc.phase1_end) // self.zc.phase2_shrink_interval
        phase3_shrinks = (self.config.max_ticks - self.zc.phase2_end) // self.zc.phase3_shrink_interval
        self.max_shrinks = phase2_shrinks + phase3_shrinks
        
        # 최종 남는 안전 구역의 반경 (기존 로직과 동일한 크기 유지)
        self.final_radius = max(0, (min(w, h) - (self.max_shrinks * 2)) // 2)
        
        # 목표 중심점을 무작위로 선택 (최종 반경이 맵을 벗어나지 않도록 여유를 둠)
        margin = self.final_radius + 2
        self.target_x = self.rng.randint(margin, w - margin - 1)
        self.target_y = self.rng.randint(margin, h - margin - 1)

    def update(self, tick: int) -> None:
        """현재 틱에 맞춰 자기장 경계를 업데이트한다."""
        if tick <= self.zc.phase1_end:
            # Phase 1: 자기장 없음
            self.current_shrink = 0
            return

        if tick <= self.zc.phase2_end:
            # Phase 2: 20틱마다 수축
            ticks_into_phase = tick - self.zc.phase1_end
            self.current_shrink = ticks_into_phase // self.zc.phase2_shrink_interval
        else:
            # Phase 3: 가속 수축
            phase2_shrinks = (
                (self.zc.phase2_end - self.zc.phase1_end)
                // self.zc.phase2_shrink_interval
            )
            ticks_into_phase3 = tick - self.zc.phase2_end
            phase3_shrinks = ticks_into_phase3 // self.zc.phase3_shrink_interval
            self.current_shrink = phase2_shrinks + phase3_shrinks

        # 최대 수축치 제한 및 호환성용 boundary 유지
        self.current_shrink = min(self.current_shrink, self.max_shrinks)
        self.boundary = self.current_shrink
        
        # 현재 진행도에 맞춰 상하좌우 경계 보간 계산 (목표지점을 향해 비대칭으로 수축)
        progress = self.current_shrink / self.max_shrinks if self.max_shrinks > 0 else 0
        w, h = self.config.map.width, self.config.map.height
        
        start_min_x, start_max_x = 0, w - 1
        start_min_y, start_max_y = 0, h - 1
        
        target_min_x, target_max_x = self.target_x - self.final_radius, self.target_x + self.final_radius
        target_min_y, target_max_y = self.target_y - self.final_radius, self.target_y + self.final_radius
        
        cur_min_x = start_min_x + int((target_min_x - start_min_x) * progress)
        cur_max_x = start_max_x - int((start_max_x - target_max_x) * progress)
        cur_min_y = start_min_y + int((target_min_y - start_min_y) * progress)
        cur_max_y = start_max_y - int((start_max_y - target_max_y) * progress)
        
        self.bounds = (cur_min_x, cur_min_y, cur_max_x, cur_max_y)

    def is_outside_safe_zone(self, pos: Position) -> bool:
        """해당 위치가 자기장 영역(위험 구역) 안에 있는지 확인."""
        if self.current_shrink <= 0:
            return False

        min_x, min_y, max_x, max_y = self.bounds
        return (
            pos.x < min_x
            or pos.x > max_x
            or pos.y < min_y
            or pos.y > max_y
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
        return self.bounds
