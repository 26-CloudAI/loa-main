import random

# MINE은 봇이 서 있는 칸을 채굴합니다.
# 광물 칸으로 이동한 다음 틱에 MINE을 실행해야 합니다.
_on_mineral = False

def action(state: dict) -> str:
    global _on_mineral

    my = state["my_bot"]
    pos_x, pos_y = my["position"]
    energy = my["energy"]
    grid = state["vision"]["grid"]
    zone_bounds = state.get("zone_bounds", (0, 0, 99, 99))
    min_x, min_y, max_x, max_y = zone_bounds

    # 존 밖이면 중심으로 이동
    in_zone = min_x <= pos_x <= max_x and min_y <= pos_y <= max_y
    if not in_zone:
        _on_mineral = False
        cx = (min_x + max_x) // 2
        cy = (min_y + max_y) // 2
        dx, dy = cx - pos_x, cy - pos_y
        if abs(dx) >= abs(dy):
            return "MOVE_RIGHT" if dx > 0 else "MOVE_LEFT"
        return "MOVE_DOWN" if dy > 0 else "MOVE_UP"

    # 에너지 위험 시 방어
    if energy <= 20:
        _on_mineral = False
        return "SHIELD"

    # 지난 틱에 광물 칸으로 이동했으면 이번 틱에 채굴
    if _on_mineral:
        _on_mineral = False
        return "MINE"

    # 8방향 인접 적 공격
    attack_dirs = [
        (0,-1,"ATTACK_UP"),    (0,1,"ATTACK_DOWN"),
        (-1,0,"ATTACK_LEFT"),  (1,0,"ATTACK_RIGHT"),
        (-1,-1,"ATTACK_UP_LEFT"),  (1,-1,"ATTACK_UP_RIGHT"),
        (-1,1,"ATTACK_DOWN_LEFT"), (1,1,"ATTACK_DOWN_RIGHT"),
    ]
    for dx, dy, atk in attack_dirs:
        if grid[2 + dy][2 + dx] == "bot_enemy":
            return atk

    # 8방향 이동 목록
    move_dirs = [
        (0,-1,"MOVE_UP"),    (0,1,"MOVE_DOWN"),
        (-1,0,"MOVE_LEFT"),  (1,0,"MOVE_RIGHT"),
        (-1,-1,"MOVE_UP_LEFT"),  (1,-1,"MOVE_UP_RIGHT"),
        (-1,1,"MOVE_DOWN_LEFT"), (1,1,"MOVE_DOWN_RIGHT"),
    ]

    # 인접 8칸에 광물이 있으면 그 칸으로 이동 후 다음 틱 MINE 예약 (희귀 우선)
    for target_cell in ("mineral_rare", "mineral"):
        for dx, dy, mv in move_dirs:
            if grid[2 + dy][2 + dx] == target_cell:
                _on_mineral = True
                return mv

    # 시야 내 광물 방향으로 이동 (8방향 최단, 희귀 우선)
    best_move = None
    best_score = -999
    for row in range(5):
        for col in range(5):
            cell = grid[row][col]
            if cell not in ("mineral", "mineral_rare"):
                continue
            ddx, ddy = col - 2, row - 2
            dist = max(abs(ddx), abs(ddy))
            score = (20 if cell == "mineral_rare" else 5) - dist
            if score > best_score:
                best_score = score
                best_move = (ddx, ddy)

    if best_move:
        ddx, ddy = best_move
        sx = (1 if ddx > 0 else -1) if ddx != 0 else 0
        sy = (1 if ddy > 0 else -1) if ddy != 0 else 0
        if grid[2 + sy][2 + sx] in ("mineral", "mineral_rare"):
            _on_mineral = True
        for dx, dy, mv in move_dirs:
            if dx == sx and dy == sy:
                return mv

    # 랜덤 탐색 (8방향)
    return random.choice([
        "MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT",
        "MOVE_UP_LEFT", "MOVE_UP_RIGHT", "MOVE_DOWN_LEFT", "MOVE_DOWN_RIGHT",
    ])
