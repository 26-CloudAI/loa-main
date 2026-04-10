"""
AI Arena — 시야(Vision) 시스템
봇 중심 5×5 격자의 정보를 추출하여 state JSON으로 변환.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .config import GameConfig
from .types import Bot, CellType, Position

if TYPE_CHECKING:
    from .grid import Grid
    from .zone import ZoneManager


def build_vision_grid(
    bot: Bot,
    all_bots: dict[str, Bot],
    grid: Grid,
    zone: ZoneManager,
    config: GameConfig,
) -> list[list[str]]:
    """
    봇 중심 5×5 시야 격자를 생성한다.
    반환값은 5×5 문자열 배열. 행(row) = y축, 열(col) = x축.
    """
    radius = config.bot.vision_radius  # 2 → 5×5
    size = radius * 2 + 1
    vision: list[list[str]] = []

    # 다른 봇 위치 → id 매핑 (빠른 조회용)
    bot_positions: dict[tuple[int, int], str] = {}
    for other in all_bots.values():
        if other.alive and other.id != bot.id:
            bot_positions[other.position.as_tuple()] = other.id

    for dy in range(-radius, radius + 1):
        row: list[str] = []
        for dx in range(-radius, radius + 1):
            wx = bot.position.x + dx
            wy = bot.position.y + dy

            if dx == 0 and dy == 0:
                row.append(CellType.ME.value)
                continue

            # 맵 밖
            if not grid.is_in_bounds(wx, wy):
                row.append(CellType.EMPTY.value)
                continue

            # 다른 봇
            if (wx, wy) in bot_positions:
                row.append(CellType.BOT_ENEMY.value)
                continue

            # 광물
            mineral = grid.get_mineral(wx, wy)
            if mineral is not None:
                if mineral.rare:
                    row.append(CellType.MINERAL_RARE.value)
                else:
                    row.append(CellType.MINERAL.value)
                continue

            row.append(CellType.EMPTY.value)

        vision.append(row)

    return vision


def build_leaderboard(all_bots: dict[str, Bot], config: GameConfig) -> list[dict]:
    """생존 봇 상위 N명의 리더보드를 반환한다. 틱당 한 번만 호출해야 한다."""
    alive = sorted(
        (b for b in all_bots.values() if b.alive),
        key=lambda b: b.score,
        reverse=True,
    )
    return [
        {"rank": rank, "id": b.id, "score": b.score}
        for rank, b in enumerate(alive[: config.leaderboard_size], start=1)
    ]


def build_bot_state(
    bot: Bot,
    all_bots: dict[str, Bot],
    grid: Grid,
    zone: ZoneManager,
    config: GameConfig,
    tick: int,
    leaderboard: list[dict] | None = None,
) -> dict:
    """봇에게 전달할 state 딕셔너리를 생성한다."""
    vision_grid = build_vision_grid(bot, all_bots, grid, zone, config)
    if leaderboard is None:
        leaderboard = build_leaderboard(all_bots, config)

    return {
        "tick": tick,
        "my_bot": {
            "id": bot.id,
            "position": [bot.position.x, bot.position.y],
            "energy": bot.energy,
            "score": bot.score,
            "shield_active": bot.shield_active,
        },
        "vision": {
            "grid": vision_grid,
        },
        "zone_boundary": zone.boundary,
        "leaderboard": leaderboard,
    }
