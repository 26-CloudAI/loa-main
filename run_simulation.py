"""
AI Arena — 시뮬레이션 실행기
콜드스타트 봇 5개로 한 판을 완주하고 결과를 콘솔에 출력한다.

사용법:
    python -m run_simulation
    python -m run_simulation --bots 10 --seed 123
"""

from __future__ import annotations

import argparse
import sys
import time
import json
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from src.arena.config import DEFAULT_CONFIG
from src.arena.engine import GameEngine
from bots.herbivore import HerbivoreBot
from bots.mad_dog import MadDogBot
from bots.camper import CamperBot


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

    # 게임 실행
    start_time = time.perf_counter()
    milestone_ticks = {50, 100, 200, 300, 400, 500}

    while not engine.game_over:
        events = engine.process_tick()
        # --------------------------------------------------------
        # 추가: 매 틱마다 발생하는 상세 라이트 수집[cite: 1]
        current_tick_data = {
            "tick": engine.tick,
            "events": [
                {
                    "type": ev.event_type, 
                    "actor": ev.actor_id, 
                    "target": getattr(ev, 'target_id', None), 
                    "detail": ev.detail
                } for ev in events
            ],
            "bots": {}
        }

        for bot_id, bot in engine.bots.items():
            # 엔진에서 방금 수집한 액션 가져오기
            action = engine.current_actions.get(bot_id) if hasattr(engine, 'current_actions') else None

            current_tick_data["bots"][bot_id] = {
                "alive": bot.alive,
                "action": action.value if action else "NONE",
                "energy": bot.energy,
                "pos": [bot.position.x, bot.position.y] if bot.alive else None,
                "score": round(bot.score, 1)
            }

        tick_lights.append(current_tick_data)
        # --------------------------------------------------------

        # 주요 이벤트 출력
        for ev in events:
            if ev.event_type in ("kill", "death"):
                print(f"  [틱 {ev.tick:4d}] {ev.detail}")

        # 마일스톤 출력
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
    
    # 추가: 시뮬레이션 종료 후 전체 라이트를 JSON 파일로 추출[cite: 1]
    with open("simulation_light.json", "w", encoding="utf-8") as f:
        json.dump(tick_lights, f, ensure_ascii=False, indent=2)
    print(f"\n💾 [안내] 전체 틱 라이트가 'simulation_light.json' 파일로 안전하게 저장되었습니다.")
    # --------------------------------------------------------


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Arena 시뮬레이션")
    parser.add_argument("--bots", type=int, default=5, help="봇 수 (기본 5)")
    parser.add_argument("--seed", type=int, default=42, help="랜덤 시드")
    parser.add_argument("-v", "--verbose", action="store_true", help="상세 출력")
    args = parser.parse_args()

    run(num_bots=args.bots, seed=args.seed, verbose=args.verbose)
