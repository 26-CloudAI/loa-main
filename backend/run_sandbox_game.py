"""
AI Arena — Docker 샌드박스 통합 실행기

실제 Docker 컨테이너 안에서 유저 봇 코드를 격리 실행하여 게임을 진행한다.

사전 조건:
  1. Docker 데몬이 실행 중이어야 한다.
  2. 'pip install docker'가 완료되어야 한다.
  3. 현재 사용자가 docker 그룹에 속해야 한다.

사용법:
    python run_sandbox_game.py
    python run_sandbox_game.py --bots 5 --seed 42 --timeout 0.2
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.arena.config import DEFAULT_CONFIG
from src.arena.engine import GameEngine
from src.arena.sandbox import ContainerPool, SandboxConfig

# ── 봇 코드 템플릿 ──

HERBIVORE_CODE = '''
import random

_rng = random.Random(42)
_on_mineral = False
_memory = {}

def action(state):
    global _on_mineral, _memory
    
    my = state["my_bot"]
    pos_x, pos_y = my["position"]
    grid = state["vision"]["grid"]
    cx, cy = 2, 2

    # 1. 시야 정보를 바탕으로 맵 기억 업데이트
    for dy in range(5):
        for dx in range(5):
            map_x, map_y = pos_x + (dx - cx), pos_y + (dy - cy)
            cell = grid[dy][dx]
            if cell in ("mineral", "mineral_rare"):
                _memory[(map_x, map_y)] = cell
            elif cell == "empty":
                _memory.pop((map_x, map_y), None)

    if _on_mineral:
        _on_mineral = False
        return "MINE"

    def move_toward(dx, dy):
        if abs(dx) >= abs(dy):
            return "MOVE_RIGHT" if dx > 0 else "MOVE_LEFT"
        return "MOVE_DOWN" if dy > 0 else "MOVE_UP"

    def flee(enemy_dx, enemy_dy):
        if abs(enemy_dx) >= abs(enemy_dy):
            return "MOVE_LEFT" if enemy_dx > 0 else "MOVE_RIGHT"
        return "MOVE_UP" if enemy_dy > 0 else "MOVE_DOWN"

    # 시야 내 적 감지 → 도주 우선
    for dy in range(5):
        for dx in range(5):
            if grid[dy][dx] == "bot_enemy":
                enemy_dx = dx - cx
                enemy_dy = dy - cy
                if abs(enemy_dx) + abs(enemy_dy) <= 2:
                    return flee(enemy_dx, enemy_dy)

    # 인접 4칸에 광물 → 이동 후 다음 틱 채굴
    adjacent = [(0, -1, "MOVE_UP"), (0, 1, "MOVE_DOWN"), (-1, 0, "MOVE_LEFT"), (1, 0, "MOVE_RIGHT")]
    for adx, ady, move in adjacent:
        cell = grid[cy + ady][cx + adx]
        if cell in ("mineral", "mineral_rare"):
            _on_mineral = True
            return move

    # 시야 내 가장 가까운 광물 방향으로 이동
    best = None
    best_dist = 999
    for dy in range(5):
        for dx in range(5):
            if grid[dy][dx] in ("mineral", "mineral_rare"):
                dist = abs(dx - cx) + abs(dy - cy)
                prio = dist - (1 if grid[dy][dx] == "mineral_rare" else 0)
                if prio < best_dist:
                    best_dist = prio
                    best = (dx - cx, dy - cy)

    if best:
        return move_toward(*best)

    # 시야에 광물이 없다면, 기억 속 가장 가까운 광물로 이동
    if _memory:
        best_mem = None
        best_mem_dist = 999
        for (mx, my), m_type in _memory.items():
            dist = abs(mx - pos_x) + abs(my - pos_y)
            prio = dist - (1 if m_type == "mineral_rare" else 0)
            if prio < best_mem_dist:
                best_mem_dist = prio
                best_mem = (mx - pos_x, my - pos_y)
        if best_mem:
            return move_toward(*best_mem)

    return _rng.choice(["MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT"])
'''

MAD_DOG_CODE = '''
import random

_rng = random.Random(99)
_memory = {}

def action(state):
    global _memory
    my = state["my_bot"]
    grid = state["vision"]["grid"]
    pos_x, pos_y = my["position"]
    energy = my["energy"]
    cx, cy = 2, 2

    # 메모리 업데이트
    for dy in range(5):
        for dx in range(5):
            map_x, map_y = pos_x + (dx - cx), pos_y + (dy - cy)
            cell = grid[dy][dx]
            if cell in ("mineral", "mineral_rare"):
                _memory[(map_x, map_y)] = cell
            elif cell == "empty":
                _memory.pop((map_x, map_y), None)

    def move_toward(dx, dy):
        if dx == 0 and dy == 0:
            return "MINE"
        if abs(dx) >= abs(dy):
            return "MOVE_RIGHT" if dx > 0 else "MOVE_LEFT"
        return "MOVE_DOWN" if dy > 0 else "MOVE_UP"

    def emergency_mine():
        if (pos_x, pos_y) in _memory:
            _memory.pop((pos_x, pos_y), None)
            return "MINE"
        adjacent = [(0, -1, "MOVE_UP"), (0, 1, "MOVE_DOWN"), (-1, 0, "MOVE_LEFT"), (1, 0, "MOVE_RIGHT")]
        for adx, ady, move in adjacent:
            if grid[cy + ady][cx + adx] in ("mineral", "mineral_rare"):
                return move
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] in ("mineral", "mineral_rare"):
                    return move_toward(dx - cx, dy - cy)
        if _memory:
            best_mem = None
            best_mem_dist = 999
            for (mx, my) in _memory.keys():
                dist = abs(mx - pos_x) + abs(my - pos_y)
                if dist < best_mem_dist:
                    best_mem_dist = dist
                    best_mem = (mx - pos_x, my - pos_y)
            if best_mem:
                return move_toward(*best_mem)
        return "SHIELD"

    # 에너지 위기 관리
    if energy <= 40:
        return emergency_mine()

    # 인접 적 공격
    adjacent_attacks = [(0, -1, "ATTACK_UP"), (0, 1, "ATTACK_DOWN"), (-1, 0, "ATTACK_LEFT"), (1, 0, "ATTACK_RIGHT")]
    for adx, ady, attack in adjacent_attacks:
        if grid[cy + ady][cx + adx] == "bot_enemy":
            return attack

    # 적 추적
    closest_enemy = None
    best_dist = 999
    for dy in range(5):
        for dx in range(5):
            if grid[dy][dx] == "bot_enemy":
                dist = abs(dx - cx) + abs(dy - cy)
                if dist < best_dist:
                    best_dist = dist
                    closest_enemy = (dx - cx, dy - cy)

    if closest_enemy:
        return move_toward(*closest_enemy)

    # 기회주의적 채굴
    if energy < 300:
        if (pos_x, pos_y) in _memory:
            _memory.pop((pos_x, pos_y), None)
            return "MINE"
        closest_mineral = None
        closest_min_dist = 999
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] in ("mineral", "mineral_rare"):
                    dist = abs(dx - cx) + abs(dy - cy)
                    if dist < closest_min_dist:
                        closest_min_dist = dist
                        closest_mineral = (dx - cx, dy - cy)
        if closest_mineral:
            return move_toward(*closest_mineral)

    # 중앙으로 이동
    cdx, cdy = 50 - pos_x, 50 - pos_y
    if abs(cdx) > 3 or abs(cdy) > 3:
        return move_toward(cdx, cdy)

    return _rng.choice(["MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT"])
'''

CAMPER_CODE = '''
import random

_rng = random.Random(77)
_memory = {}
_last_energy = 100
_last_action = "STAY"

def action(state):
    global _memory, _last_energy, _last_action
    
    my = state["my_bot"]
    grid = state["vision"]["grid"]
    tick = state["tick"]
    pos_x, pos_y = my["position"]
    energy = my["energy"]
    cx, cy = 2, 2

    danger_inferred = False
    cost_map = {
        "STAY": 1, "MINE": 3, "SHIELD": 3,
        "MOVE_UP": 2, "MOVE_DOWN": 2, "MOVE_LEFT": 2, "MOVE_RIGHT": 2,
        "ATTACK_UP": 5, "ATTACK_DOWN": 5, "ATTACK_LEFT": 5, "ATTACK_RIGHT": 5
    }
    expected_loss = cost_map.get(_last_action, 1)

    if energy < _last_energy:
        if (_last_energy - energy) > expected_loss:
            danger_inferred = True
    else:
        gain = energy - _last_energy
        if gain in (4, 19):
            danger_inferred = True

    _last_energy = energy

    for dy in range(5):
        for dx in range(5):
            map_x, map_y = pos_x + (dx - cx), pos_y + (dy - cy)
            cell = grid[dy][dx]
            if cell in ("mineral", "mineral_rare"):
                _memory[(map_x, map_y)] = cell
            elif cell == "empty":
                _memory.pop((map_x, map_y), None)

    def move_toward(dx, dy):
        if dx == 0 and dy == 0:
            return "STAY"
        if abs(dx) >= abs(dy):
            return "MOVE_RIGHT" if dx > 0 else "MOVE_LEFT"
        return "MOVE_DOWN" if dy > 0 else "MOVE_UP"

    def flee(enemy_dx, enemy_dy):
        if abs(enemy_dx) >= abs(enemy_dy):
            return "MOVE_LEFT" if enemy_dx > 0 else "MOVE_RIGHT"
        return "MOVE_UP" if enemy_dy > 0 else "MOVE_DOWN"

    zone_dx, zone_dy = 0, 0
    zone_count = 0
    for dy in range(5):
        for dx in range(5):
            if grid[dy][dx] == "zone":
                zone_dx += (dx - cx)
                zone_dy += (dy - cy)
                zone_count += 1
    
    if zone_count > 0:
        _last_action = flee(zone_dx, zone_dy)
        return _last_action

    for dy in range(5):
        for dx in range(5):
            if grid[dy][dx] == "bot_enemy":
                dist = abs(dx - cx) + abs(dy - cy)
                if dist == 1:
                    if energy > 20:
                        _last_action = "SHIELD"
                        return _last_action
                    _last_action = flee(dx - cx, dy - cy)
                    return _last_action
                if dist == 2:
                    _last_action = flee(dx - cx, dy - cy)
                    return _last_action

    if danger_inferred:
        _last_action = move_toward(50 - pos_x, 50 - pos_y)
        return _last_action

    if (pos_x, pos_y) in _memory:
        _memory.pop((pos_x, pos_y), None)
        _last_action = "MINE"
        return _last_action

    closest_mineral = None
    closest_dist = 999
    for dy in range(5):
        for dx in range(5):
            if grid[dy][dx] in ("mineral", "mineral_rare"):
                dist = abs(dx - cx) + abs(dy - cy)
                if dist < closest_dist:
                    closest_dist = dist
                    closest_mineral = (dx - cx, dy - cy)
    if closest_mineral:
        _last_action = move_toward(*closest_mineral)
        return _last_action

    if _memory:
        best_mem = None
        best_mem_dist = 999
        for (mx, my) in _memory.keys():
            dist = abs(mx - pos_x) + abs(my - pos_y)
            if dist < best_mem_dist:
                best_mem_dist = dist
                best_mem = (mx - pos_x, my - pos_y)
        if best_mem:
            _last_action = move_toward(*best_mem)
            return _last_action

    if pos_x <= 20 and pos_y < 80:
        _last_action = "MOVE_DOWN"
        return _last_action
    if pos_y >= 80 and pos_x < 80:
        _last_action = "MOVE_RIGHT"
        return _last_action
    if pos_x >= 80 and pos_y > 20:
        _last_action = "MOVE_UP"
        return _last_action
    if pos_y <= 20 and pos_x > 20:
        _last_action = "MOVE_LEFT"
        return _last_action
        
    _last_action = move_toward(15 - pos_x, 15 - pos_y)
    return _last_action
'''

# 의도적 무한루프 봇 (악성 코드 테스트)
MALICIOUS_CODE = '''
def action(state):
    while True:  # 무한루프 — 타임아웃으로 잡혀야 함
        pass
    return "STAY"
'''

BOT_TEMPLATES = {
    "herbivore": HERBIVORE_CODE,
    "mad_dog": MAD_DOG_CODE,
    "camper": CAMPER_CODE,
}


def create_bot_codes(num_bots: int, include_malicious: bool = False) -> dict[str, str]:
    """봇 코드 딕셔너리 생성."""
    codes = {}
    labels = list(BOT_TEMPLATES.keys())

    for i in range(num_bots):
        label = labels[i % len(labels)]
        bot_id = f"{label}_{i:02d}"
        codes[bot_id] = BOT_TEMPLATES[label]

    if include_malicious:
        codes["malicious_99"] = MALICIOUS_CODE

    return codes


def run(
    num_bots: int = 3,
    seed: int = 42,
    timeout: float = 0.1,
    include_malicious: bool = False,
):
    print("=" * 60)
    print(f"  AI Arena 샌드박스 시뮬레이션")
    print(f"  봇 {num_bots}개 | 시드 {seed} | 타임아웃 {timeout}s")
    if include_malicious:
        print(f"  ⚠ 악성 봇 포함 (무한루프 테스트)")
    print("=" * 60)
    print()

    bot_codes = create_bot_codes(num_bots, include_malicious)
    sandbox_cfg = SandboxConfig(action_timeout_sec=timeout)

    print("[1/4] Docker 컨테이너 풀 시작...")
    start = time.perf_counter()

    with ContainerPool(bot_codes, config=sandbox_cfg) as pool:
        pool_time = time.perf_counter() - start
        print(f"  ✓ {len(bot_codes)}개 컨테이너 기동 완료 ({pool_time:.2f}초)")

        adapters = pool.get_adapters()

        print(f"\n[2/4] 게임 엔진 초기화...")
        engine = GameEngine(adapters, config=DEFAULT_CONFIG, seed=seed)

        print(f"  맵: {DEFAULT_CONFIG.map.width}×{DEFAULT_CONFIG.map.height}")
        print(f"  광물: {engine.grid.count_available_minerals()}개")
        print()

        # 봇 위치 출력
        for bot_id, bot in engine.bots.items():
            print(f"  {bot_id:12s} → ({bot.position.x:3d}, {bot.position.y:3d})")
        print()

        print("[3/4] 게임 실행 중...")
        game_start = time.perf_counter()
        milestone_ticks = {50, 100, 200, 300, 400, 500}

        while not engine.game_over:
            events = engine.process_tick()

            for ev in events:
                if ev.event_type in ("kill", "death"):
                    print(f"  [틱 {ev.tick:4d}] {ev.detail}")

            if engine.tick in milestone_ticks:
                alive = engine.get_alive_bots()
                minerals = engine.grid.count_available_minerals()
                print(
                    f"  [틱 {engine.tick:4d}] "
                    f"생존: {len(alive)} | 광물: {minerals} | "
                    f"자기장: {engine.zone.boundary}"
                )

        game_time = time.perf_counter() - game_start

        # 결과
        result = engine.game_result
        assert result is not None

        print()
        print("=" * 60)
        print(f"  게임 종료 — {result.reason.value}")
        print(f"  최종 틱: {result.final_tick} | 게임 소요: {game_time:.2f}초")
        print("=" * 60)
        print()

        print(f"{'순위':>4} {'봇 ID':>12} {'최종점수':>10} {'채굴':>6} "
              f"{'킬':>4} {'생존틱':>7} {'에너지':>7} {'생존':>4}")
        print("-" * 60)

        for r in result.rankings:
            alive_mark = "✓" if r["alive"] else "✗"
            print(
                f"{r['rank']:>4} {r['id']:>12} {r['final_score']:>10.1f} "
                f"{r['minerals_mined']:>6} {r['kills']:>4} "
                f"{r['survival_ticks']:>7} {r['energy']:>7} {alive_mark:>4}"
            )

        print(f"\n🏆 우승: {result.rankings[0]['id']} "
              f"({result.rankings[0]['final_score']:.1f}점)")

        # 통신 통계
        print(f"\n[4/4] 컨테이너 통신 통계:")
        for stats in pool.get_all_stats():
            print(
                f"  {stats['bot_id']:>12} | "
                f"호출: {stats['total_calls']:>5} | "
                f"타임아웃: {stats['timeout_count']:>4} | "
                f"오류: {stats['error_count']:>4} | "
                f"성공률: {stats['success_rate']:.1%}"
            )

    total_time = time.perf_counter() - start
    print(f"\n총 소요 시간 (컨테이너 생성+게임+정리): {total_time:.2f}초")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Arena 샌드박스 시뮬레이션")
    parser.add_argument("--bots", type=int, default=3, help="봇 수 (기본 3)")
    parser.add_argument("--seed", type=int, default=42, help="랜덤 시드")
    parser.add_argument("--timeout", type=float, default=0.1, help="액션 타임아웃 (초)")
    parser.add_argument("--malicious", action="store_true", help="악성 봇 포함")
    args = parser.parse_args()

    run(
        num_bots=args.bots,
        seed=args.seed,
        timeout=args.timeout,
        include_malicious=args.malicious,
    )
