"""
AI Arena — Docker 샌드박스 통합 실행기 (로그 기록 버전)

실제 Docker 컨테이너 안에서 유저 봇 코드를 격리 실행하여 게임을 진행하고,
모든 틱의 상세 정보를 logs/ 폴더에 JSON 형태로 저장한다.

사전 조건:
  1. Docker 데몬이 실행 중이어야 한다.
  2. 'pip install docker'가 완료되어야 한다.
  3. 현재 사용자가 docker 그룹에 속해야 한다.

사용법:
    python run_sandbox_game_log.py
    python run_sandbox_game_log.py --bots 5 --seed 42 --timeout 0.2
"""

from __future__ import annotations

import argparse
import sys
import time
import json
from datetime import datetime
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

def action(state):
    global _on_mineral
    grid = state["vision"]["grid"]
    cx, cy = 2, 2

    if _on_mineral:
        _on_mineral = False
        return "MINE"

    # 적 회피
    for dy in range(5):
        for dx in range(5):
            if grid[dy][dx] == "bot_enemy":
                dist = abs(dx - cx) + abs(dy - cy)
                if dist <= 2:
                    edx, edy = dx - cx, dy - cy
                    if abs(edx) >= abs(edy):
                        return "MOVE_LEFT" if edx > 0 else "MOVE_RIGHT"
                    return "MOVE_UP" if edy > 0 else "MOVE_DOWN"

    # 인접 광물 이동
    for adx, ady, move in [(0,-1,"MOVE_UP"),(0,1,"MOVE_DOWN"),(-1,0,"MOVE_LEFT"),(1,0,"MOVE_RIGHT")]:
        if grid[cy+ady][cx+adx] in ("mineral", "mineral_rare"):
            _on_mineral = True
            return move

    # 시야 내 광물 방향 이동
    for dy in range(5):
        for dx in range(5):
            if grid[dy][dx] in ("mineral", "mineral_rare"):
                mdx, mdy = dx - cx, dy - cy
                if abs(mdx) >= abs(mdy):
                    return "MOVE_RIGHT" if mdx > 0 else "MOVE_LEFT"
                return "MOVE_DOWN" if mdy > 0 else "MOVE_UP"

    return _rng.choice(["MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT"])
'''

MAD_DOG_CODE = '''
import random

_rng = random.Random(99)

def action(state):
    my = state["my_bot"]
    grid = state["vision"]["grid"]
    energy = my["energy"]
    pos_x, pos_y = my["position"]
    cx, cy = 2, 2

    if energy <= 15:
        return "SHIELD"

    # 인접 적 공격
    for adx, ady, atk in [(0,-1,"ATTACK_UP"),(0,1,"ATTACK_DOWN"),(-1,0,"ATTACK_LEFT"),(1,0,"ATTACK_RIGHT")]:
        if grid[cy+ady][cx+adx] == "bot_enemy":
            return atk

    # 적 추적
    closest = None
    best_dist = 999
    for dy in range(5):
        for dx in range(5):
            if grid[dy][dx] == "bot_enemy":
                dist = abs(dx - cx) + abs(dy - cy)
                if dist < best_dist:
                    best_dist = dist
                    closest = (dx - cx, dy - cy)

    if closest:
        mdx, mdy = closest
        if abs(mdx) >= abs(mdy):
            return "MOVE_RIGHT" if mdx > 0 else "MOVE_LEFT"
        return "MOVE_DOWN" if mdy > 0 else "MOVE_UP"

    # 중앙으로 이동
    cdx, cdy = 50 - pos_x, 50 - pos_y
    if abs(cdx) > 3 or abs(cdy) > 3:
        if abs(cdx) >= abs(cdy):
            return "MOVE_RIGHT" if cdx > 0 else "MOVE_LEFT"
        return "MOVE_DOWN" if cdy > 0 else "MOVE_UP"

    return _rng.choice(["MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT"])
'''

CAMPER_CODE = '''
import random

_rng = random.Random(77)

def action(state):
    my = state["my_bot"]
    grid = state["vision"]["grid"]
    tick = state["tick"]
    zone = state["zone_boundary"]
    pos_x, pos_y = my["position"]
    energy = my["energy"]
    cx, cy = 2, 2

    # 인접 적 → 실드/회피
    for dy in range(5):
        for dx in range(5):
            if grid[dy][dx] == "bot_enemy":
                dist = abs(dx - cx) + abs(dy - cy)
                if dist == 1 and energy > 20:
                    return "SHIELD"
                if dist <= 2:
                    edx, edy = dx - cx, dy - cy
                    if abs(edx) >= abs(edy):
                        return "MOVE_LEFT" if edx > 0 else "MOVE_RIGHT"
                    return "MOVE_UP" if edy > 0 else "MOVE_DOWN"

    # 자기장 회피
    if zone > 0:
        safe_min = zone + 2
        safe_max = 99 - zone - 2
        if pos_x < safe_min: return "MOVE_RIGHT"
        if pos_x > safe_max: return "MOVE_LEFT"
        if pos_y < safe_min: return "MOVE_DOWN"
        if pos_y > safe_max: return "MOVE_UP"

    # 후반 채굴
    if tick >= 250:
        for adx, ady, move in [(0,-1,"MOVE_UP"),(0,1,"MOVE_DOWN"),(-1,0,"MOVE_LEFT"),(1,0,"MOVE_RIGHT")]:
            if grid[cy+ady][cx+adx] in ("mineral", "mineral_rare"):
                return move

    if tick < 100:
        return "STAY"

    if _rng.random() < 0.3:
        return _rng.choice(["MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT"])
    return "STAY"
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
    print(f"  AI Arena 샌드박스 시뮬레이션 (로그 기록용)")
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

        # 전체 틱 데이터를 모아둘 빈 리스트 및 생존 상태 초기화
        tick_lights = []
        previous_alive = {bot_id: True for bot_id in engine.bots.keys()}

        while not engine.game_over:
            events = engine.process_tick()

            current_tick_data = {
                "tick": engine.tick,
                "zone_boundary": engine.zone.boundary,
                "events": [
                    {
                        "type": ev.event_type, 
                        "actor": getattr(ev, 'actor_id', None), 
                        "target": getattr(ev, 'target_id', None), 
                        "detail": ev.detail
                    } for ev in events
                ],
                "bots": {},
                "minerals": []
            }

            # 자연사(에너지 고갈) 라이트 강제 생성 로직
            for bot_id, bot in engine.bots.items():
                if previous_alive[bot_id] and not bot.alive:
                    has_death_light = any(
                        e["type"] in ("kill", "death") and e["target"] == bot_id 
                        for e in current_tick_data["events"]
                    )
                    
                    if not has_death_light:
                        current_tick_data["events"].append({
                            "type": "death",
                            "actor": None,
                            "target": bot_id,
                            "detail": "행동 비용 또는 대기로 인해 에너지가 고갈되었습니다."
                        })
                        
                previous_alive[bot_id] = bot.alive

            # 광물 위치 수집
            for y in range(DEFAULT_CONFIG.map.height):
                for x in range(DEFAULT_CONFIG.map.width):
                    mineral = engine.grid.get_mineral(x, y)
                    if mineral:
                        current_tick_data["minerals"].append({
                            "x": x, 
                            "y": y, 
                            "rare": mineral.rare
                        })

            # 봇 상태 수집
            for bot_id, bot in engine.bots.items():
                action = engine.current_actions.get(bot_id) if hasattr(engine, 'current_actions') else None
                action_val = "NONE"
                if action:
                    action_val = action.value if hasattr(action, 'value') else str(action)
                
                current_tick_data["bots"][bot_id] = {
                    "alive": bot.alive,
                    "action": action_val,
                    "energy": bot.energy,
                    "pos": [bot.position.x, bot.position.y] if bot.alive else None,
                    "score": round(bot.score, 1)
                }

            # 이번 틱의 데이터를 전체 리스트에 안전하게 저장!
            tick_lights.append(current_tick_data)

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

        # --------------------------------------------------------
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)  # logs 폴더가 없으면 자동으로 생성

        # 현재 시간을 'YYYYMMDD_HHMMSS' 형태로 가져오기
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = log_dir / f"sandbox_light_{current_time}.json"

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(tick_lights, f, ensure_ascii=False, indent=2)
            
        print(f"\n💾 [안내] 샌드박스 전체 틱 라이트가 '{file_path}' 파일로 안전하게 저장되었습니다.")
        # --------------------------------------------------------

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
    parser = argparse.ArgumentParser(description="AI Arena 샌드박스 시뮬레이션 (로그 포함)")
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