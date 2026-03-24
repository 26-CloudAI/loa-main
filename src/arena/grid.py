"""
AI Arena — 맵 그리드 관리
광물 배치, 봇 스폰 위치 계산, 광물 재생 로직.
"""

from __future__ import annotations

import random
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
        """초기 광물을 맵에 배치한다. 중앙은 고밀도, 코너에 희귀 광물."""
        mc = self.config.map
        target_count = mc.initial_mineral_count

        # 모든 셀에 가중치 부여
        weighted_cells: list[tuple[int, int, float, bool]] = []

        half_center = mc.center_zone_size // 2
        cx, cy = self.width // 2, self.height // 2

        for x in range(self.width):
            for y in range(self.height):
                weight = 1.0
                rare = False

                # 중앙 고밀도 구역
                if abs(x - cx) < half_center and abs(y - cy) < half_center:
                    weight = mc.center_density_multiplier

                # 코너 희귀 구역 판별
                if self._is_in_rare_zone(x, y):
                    if self.rng.random() < mc.rare_mineral_ratio:
                        rare = True

                weighted_cells.append((x, y, weight, rare))

        # 가중치 기반 랜덤 샘플링
        weights = [w for _, _, w, _ in weighted_cells]
        total_weight = sum(weights)
        probs = [w / total_weight for w in weights]

        # 중복 없이 target_count개 선택
        indices = list(range(len(weighted_cells)))
        chosen = set()
        attempts = 0
        max_attempts = target_count * 10

        while len(chosen) < target_count and attempts < max_attempts:
            idx = self.rng.choices(indices, weights=probs, k=1)[0]
            if idx not in chosen:
                chosen.add(idx)
            attempts += 1

        for idx in chosen:
            x, y, _, rare = weighted_cells[idx]
            pos = Position(x, y)
            self._minerals[(x, y)] = Mineral(position=pos, rare=rare)

    def _is_in_rare_zone(self, x: int, y: int) -> bool:
        """해당 좌표가 코너 희귀 광물 구역에 속하는지 판별."""
        rz = self.config.map.rare_zone_size
        w, h = self.width, self.height
        corners = [
            (0, 0),                     # 좌상단
            (w - rz, 0),                # 우상단
            (0, h - rz),                # 좌하단
            (w - rz, h - rz),           # 우하단
        ]
        for cx, cy in corners:
            if cx <= x < cx + rz and cy <= y < cy + rz:
                return True
        return False

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
    config: GameConfig, num_bots: int, rng: random.Random
) -> list[Position]:
    """
    봇 스폰 위치를 4개 코너 근처에 분산 배치한다.
    봇 수가 4의 배수가 아닐 때도 균등 분배.
    """
    margin = config.bot.spawn_margin
    w, h = config.map.width, config.map.height

    corners = [
        (0, 0),                         # 좌상단
        (w - margin, 0),                # 우상단
        (0, h - margin),                # 좌하단
        (w - margin, h - margin),       # 우하단
    ]

    positions: list[Position] = []
    used: set[tuple[int, int]] = set()

    for i in range(num_bots):
        corner_x, corner_y = corners[i % 4]

        # 해당 코너 내 랜덤 위치 (겹치지 않게)
        attempts = 0
        while attempts < 100:
            x = corner_x + rng.randint(0, margin - 1)
            y = corner_y + rng.randint(0, margin - 1)
            # 맵 경계 클램핑
            x = min(x, w - 1)
            y = min(y, h - 1)
            if (x, y) not in used:
                used.add((x, y))
                positions.append(Position(x, y))
                break
            attempts += 1
        else:
            # fallback: 겹치더라도 배치
            positions.append(Position(x, y))

    return positions
