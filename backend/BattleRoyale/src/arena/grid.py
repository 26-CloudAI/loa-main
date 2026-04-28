"""
AI Arena — 맵 그리드 관리
광물 배치, 봇 스폰 위치 계산, 광물 재생 로직.
"""

from __future__ import annotations

import random
import math
from typing import Optional

from .config import GameConfig
from .types import Mineral, Position


class Grid:
    """100×100 게임 맵. 광물 배치와 조회를 담당한다."""

    def __init__(self, config: GameConfig, rng: random.Random):
        self.config = config
        self.rng = rng
        self.width = config.map.width
        self.height = config.map.height

        # 좌표 → Mineral 매핑 (활성/비활성 모두 포함)
        self._minerals: dict[tuple[int, int], Mineral] = {}

        self._place_initial_minerals()

    def _place_initial_minerals(self) -> None:
        """
        초기 광물을 맵에 배치한다.
        1. 맵의 랜덤 위치에 희귀 광물 군락을 생성한다.
        2. 나머지 공간에 일반 광물을 중앙 고밀도로 배치한다.
        """
        mc = self.config.map
        
        occupied_positions = self._place_rare_clusters()
        
        num_normal_minerals = mc.initial_mineral_count - len(occupied_positions)
        if num_normal_minerals <= 0:
            return

        # 일반 광물 배치 (중앙 고밀도 적용)
        weighted_cells: list[tuple[int, int, float]] = []
        half_center = mc.center_zone_size // 2
        cx, cy = self.width // 2, self.height // 2

        for x in range(self.width):
            for y in range(self.height):
                if (x, y) in occupied_positions:
                    continue
                
                weight = 1.0
                # 중앙 고밀도 구역
                if abs(x - cx) < half_center and abs(y - cy) < half_center:
                    weight = mc.center_density_multiplier
                weighted_cells.append((x, y, weight))
        
        if not weighted_cells:
            return

        weights = [w for _, _, w in weighted_cells]
        indices = list(range(len(weighted_cells)))
        chosen_indices = self.rng.choices(
            indices, weights=weights, k=min(num_normal_minerals, len(indices))
        )

        for idx in chosen_indices:
            x, y, _ = weighted_cells[idx]
            if (x, y) not in self._minerals:
                 pos = Position(x, y)
                 self._minerals[(x, y)] = Mineral(position=pos, rare=False)


    def _place_rare_clusters(self) -> set[tuple[int, int]]:
        """맵의 랜덤 위치에 희귀 광물 군락을 생성하고, 차지된 위치를 반환."""
        mc = self.config.map
        occupied = set()

        margin = mc.rare_zone_size + 2
        # 맵이 너무 작으면 희귀 군락 배치 생략
        if margin >= self.width - margin or margin >= self.height - margin:
            return occupied

        for _ in range(mc.num_rare_mineral_clusters):
            cx = self.rng.randint(margin, self.width - margin - 1)
            cy = self.rng.randint(margin, self.height - margin - 1)

            for _ in range(mc.rare_minerals_per_cluster):
                attempts = 0
                while attempts < 20:
                    angle = self.rng.uniform(0, math.tau)
                    radius = self.rng.uniform(0, mc.rare_zone_size)
                    
                    x = int(cx + radius * math.cos(angle))
                    y = int(cy + radius * math.sin(angle))

                    if self.is_in_bounds(x, y) and (x, y) not in occupied:
                        pos = Position(x, y)
                        self._minerals[(x, y)] = Mineral(position=pos, rare=True)
                        occupied.add((x,y))
                        break
                    attempts += 1
        return occupied

    def get_mineral(self, x: int, y: int) -> Optional[Mineral]:
        """해당 좌표의 채굴 가능한 광물을 반환. 없거나 이미 채굴됐으면 None."""
        mineral = self._minerals.get((x, y))
        if mineral and mineral.is_available:
            return mineral
        return None

    def mark_mined(self, x: int, y: int, tick: int) -> None:
        """광물을 채굴 완료로 표시."""
        mineral = self._minerals.get((x, y))
        if mineral:
            mineral.mined_at_tick = tick

    def try_regen_minerals(self, current_tick: int) -> list[Position]:
        """재생 조건을 만족하는 광물을 복구. 복구된 좌표 목록 반환."""
        mc = self.config.map
        regenerated = []

        for key, mineral in self._minerals.items():
            if mineral.mined_at_tick is None:
                continue
            elapsed = current_tick - mineral.mined_at_tick
            if elapsed >= mc.mineral_regen_delay:
                if self.rng.random() < mc.mineral_regen_chance:
                    mineral.mined_at_tick = None
                    regenerated.append(mineral.position)

        return regenerated

    def count_available_minerals(self) -> int:
        """현재 채굴 가능한 광물 수."""
        return sum(1 for m in self._minerals.values() if m.is_available)

    def all_minerals_depleted(self) -> bool:
        """모든 광물이 소진되었는지 확인. (재생 대기 중인 것도 소진으로 간주)"""
        return self.count_available_minerals() == 0

    def get_all_mineral_positions(self) -> list[tuple[int, int, bool]]:
        """(x, y, rare) 형태의 채굴 가능한 광물 위치 목록."""
        result = []
        for (x, y), mineral in self._minerals.items():
            if mineral.is_available:
                result.append((x, y, mineral.rare))
        return result

    def is_in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height


def generate_spawn_positions(
    cfg: GameConfig, n: int, rng: random.Random
) -> list[Position]:
    """
    spawn_margin을 적용한 스폰 가능 영역에서 n개의 중복 없는 위치를 반환.
    """
    margin = cfg.bot.spawn_margin
    candidates = [
        Position(x, y)
        for x in range(margin, cfg.map.width - margin)
        for y in range(margin, cfg.map.height - margin)
    ]
    rng.shuffle(candidates)
    return candidates[:n]


