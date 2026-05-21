"""
AI Arena — 시뮬레이션 실행기
콜드스타트 봇 5개로 한 판을 완주하고 결과를 콘솔에 출력한다.

사용법:
    python -m run_simulation_log
    python -m run_simulation_log --bots 10 --seed 123
    
"""

from __future__ import annotations

import argparse
import sys
import time
import json
from datetime import datetime
from pathlib import Path

# battle_royale 루트(src/, bots/) + backend 루트(core/) 모두 sys.path에 추가
_BR_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_BR_ROOT))
sys.path.insert(0, str(_BR_ROOT.parent))

from core.config import DEFAULT_CONFIG
from core.engine import GameEngine
from bots.battle_royale.herbivore import HerbivoreBot
from bots.battle_royale.mad_dog import MadDogBot
from bots.battle_royale.camper import CamperBot


def create_bots(num_bots: int, seed: int) -> list:
    """봇 3종류를 라운드로빈으로 생성."""
    bot_classes = [HerbivoreBot, MadDogBot, CamperBot]
    bot_labels = ["초식", "미친개", "존버"]
    bots = []

    for i in range(num_bots):
        cls_idx = i % len(bot_classes)
        bot_id = f"{bot_labels[cls_idx]}_{i:02d}"
        bot = bot_classes[cls_idx](bot_id=bot_id, seed=seed + i)
        bots.append(bot)

    return bots


def run(num_bots: int = 5, seed: int = 42, verbose: bool = False):
    print("=" * 60)
    print(f"  AI Arena 시뮬레이션 — 봇 {num_bots}개 | 시드 {seed}")
    print("=" * 60)
    print()

    bots = create_bots(num_bots, seed)
    engine = GameEngine(bots, config=DEFAULT_CONFIG, seed=seed)

    print(f"맵: {DEFAULT_CONFIG.map.width}×{DEFAULT_CONFIG.map.height}")
    print(f"광물: {engine.grid.count_available_minerals()}개")
    print(f"최대 틱: {DEFAULT_CONFIG.max_ticks}")
    print()

    # 봇 초기 위치 출력
    print("[스폰 위치]")
    for bot_id, bot in engine.bots.items():
        print(f"  {bot_id:12s} → ({bot.position.x:3d}, {bot.position.y:3d})")
    print()

    # 전체 틱 데이터를 모아둘 빈 리스트 생성[cite: 1]
    tick_lights = []
    start_time = time.perf_counter()
    milestone_ticks = {50, 100, 150, 200}

    # [추가] 반복문 시작 전에 딱 한 번만 선언!
    previous_alive = {bot_id: True for bot_id in engine.bots.keys()}

    # 반복문은 무조건 한 번만 돌아야 합니다.
    while not engine.game_over:
        events = engine.process_tick()

        current_tick_data = {
            "tick": engine.tick,
            "zone_boundary": engine.zone.boundary,
            "zone_bounds": engine.zone.bounds,
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

        # --------------------------------------------------------
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
        # --------------------------------------------------------

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
            current_tick_data["bots"][bot_id] = {
                "alive": bot.alive,
                "action": action.value if action else "NONE",
                "energy": bot.energy,
                "pos": [bot.position.x, bot.position.y] if bot.alive else None,
                "score": round(bot.score, 1),
                "shield_active": bot.shield_active
            }

        # 이번 틱의 데이터를 전체 리스트에 안전하게 저장!
        tick_lights.append(current_tick_data)

        # 기존 콘솔 출력 유지
        for ev in events:
            if ev.event_type in ("kill", "death", "guard_success"):
                print(f"  [틱 {ev.tick:4d}] {ev.detail}")

        if engine.tick in milestone_ticks:
            alive = engine.get_alive_bots()
            minerals = engine.grid.count_available_minerals()
            print(
                f"  [틱 {engine.tick:4d}] "
                f"생존: {len(alive)} | "
                f"광물: {minerals} | "
                f"자기장: {engine.zone.boundary}"
            )

    elapsed = time.perf_counter() - start_time

    # 결과 출력
    result = engine.game_result
    assert result is not None

    print()
    print("=" * 60)
    print(f"  게임 종료 — {result.reason.value}")
    print(f"  최종 틱: {result.final_tick} | 소요: {elapsed:.3f}초")
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

    print()
    print(f"🏆 우승: {result.rankings[0]['id']} "
          f"({result.rankings[0]['final_score']:.1f}점)")
    
    # --------------------------------------------------------
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)  # logs 폴더가 없으면 자동으로 생성

    # 현재 시간을 'YYYYMMDD_HHMMSS' 형태로 가져오기
    current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = log_dir / f"simulation_light_{current_time}.json"

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(tick_lights, f, ensure_ascii=False, indent=2)
        
    print(f"\n💾 [안내] 전체 틱 라이트가 '{file_path}' 파일로 안전하게 저장되었습니다.")
    # --------------------------------------------------------


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Arena 시뮬레이션")
    parser.add_argument("--bots", type=int, default=5, help="봇 수 (기본 5)")
    parser.add_argument("--seed", type=int, default=42, help="랜덤 시드")
    parser.add_argument("-v", "--verbose", action="store_true", help="상세 출력")
    args = parser.parse_args()

    run(num_bots=args.bots, seed=args.seed, verbose=args.verbose)
