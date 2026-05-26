"""
Claude vs 보스봇 시뮬레이션

ClaudeBot 1명 + 조력자 유저봇 2명 vs RuleBossEasyBot (하 난이도)
boss_battle_config() 기준 실행.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_BR_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_BR_ROOT))
sys.path.insert(0, str(_BR_ROOT.parent))

from core.engine import GameEngine
from src.arena.server.boss.config import boss_battle_config
from bots.boss.claude_bot import ClaudeBot
from bots.boss.rule_boss_bot import RuleBossEasyBot, RuleBossMediumBot
from bots.boss.rl_boss_bot import RLBossBot
from bots.battle_royale.herbivore import HerbivoreBot
from bots.battle_royale.camper import CamperBot


def run(seed: int = 42, verbose: bool = True):
    cfg = boss_battle_config()

    bots = [
        ClaudeBot(bot_id="Claude",  seed=seed),
        HerbivoreBot(bot_id="초식1", seed=seed + 1),
        CamperBot(bot_id="존버1",   seed=seed + 2),
        RLBossBot(bot_id="AI_보스", seed=seed + 99),
    ]

    engine = GameEngine(bots, config=cfg, seed=seed)

    print("=" * 62)
    print("  Claude vs 보스봇 (상 난이도 — RL DQN)  |  seed:", seed)
    print(f"  맵 {cfg.map.width}×{cfg.map.height}  |  최대 틱 {cfg.max_ticks}")
    print("=" * 62)
    print("[스폰]")
    for bot_id, bot in engine.bots.items():
        tag = " ← 나!" if bot_id == "Claude" else ""
        print(f"  {bot_id:10s} ({bot.position.x:3d}, {bot.position.y:3d}){tag}")
    print()

    milestones = {50, 100, 150, 200, 250, 300, 350, 400}
    start = time.perf_counter()

    while not engine.game_over:
        events = engine.process_tick()
        for ev in events:
            if ev.event_type in ("kill", "death") and verbose:
                print(f"  [틱 {ev.tick:4d}] {ev.detail}")

        if engine.tick in milestones and verbose:
            alive = engine.get_alive_bots()
            alive_ids = ", ".join(b.id for b in alive)
            print(f"  [틱 {engine.tick:4d}] 생존: [{alive_ids}]  "
                  f"자기장: {engine.zone.boundary}")

    elapsed = time.perf_counter() - start
    result  = engine.game_result

    print()
    print("=" * 62)
    print(f"  게임 종료 — {result.reason.value}  ({elapsed:.2f}s)")
    print("=" * 62)
    print(f"{'순위':>4} {'봇':>10} {'점수':>8} {'채굴':>6} {'킬':>4} {'생존틱':>6} {'에너지':>7} {'생존':>4}")
    print("-" * 62)

    claude_rank = None
    boss_rank   = None
    for r in result.rankings:
        mark = ""
        if r["id"] == "Claude":
            mark = " ←"
            claude_rank = r["rank"]
        elif r["id"] == "AI_보스":
            mark = " (BOSS)"
            boss_rank = r["rank"]
        alive_mark = "✓" if r["alive"] else "✗"
        print(
            f"{r['rank']:>4} {r['id']:>10} {r['final_score']:>8.1f} "
            f"{r['minerals_mined']:>6} {r['kills']:>4} "
            f"{r['survival_ticks']:>6} {r['energy']:>7} {alive_mark:>4}{mark}"
        )

    print()
    if claude_rank is not None and boss_rank is not None:
        if claude_rank < boss_rank:
            print("  결과: Claude 승리!")
        elif claude_rank == boss_rank:
            print("  결과: 동점")
        else:
            print("  결과: 보스 승리...")
    print(f"  우승: {result.rankings[0]['id']} ({result.rankings[0]['final_score']:.1f}점)")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--trials", type=int, default=1)
    args = p.parse_args()

    if args.trials == 1:
        run(seed=args.seed)
    else:
        wins = 0
        for i in range(args.trials):
            print(f"\n=== Trial {i+1}/{args.trials} (seed={args.seed + i}) ===")
            run(seed=args.seed + i, verbose=False)
            wins += 1  # 결과 집계는 verbose=False 때는 생략
        print(f"\n{args.trials}판 완료")
