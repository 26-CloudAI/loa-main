"""
보스봇 baseline 벤치마크
==========================

현재 RLBossBot(numpy 서빙)의 시나리오별 성능을 측정한다.
B 트랙(self-play league) 도입 전/후 비교 및 M3 catastrophic forgetting
모니터링의 기준선으로 사용한다.

시나리오 (5봇 게임 = 보스 1 + 상대 4):
  easy        보스 vs RuleBossEasy   ×4   (M3 floor 1: 룰봇 하 망각 방어)
  medium      보스 vs RuleBossMedium ×4   (M3 floor 2: 룰봇 중 망각 방어)
  claude_mix  보스 vs Claude + Herbi×2 + Camper   (현재 27% 기준 재현)
  sample_mix  보스 vs Duelist + Optimizer + Adaptor + ShieldTank
              (실유저 다양성 풀 근사 — Self-play league 도입 후 메타 적응 확인용)

학습 비활성화: epsilon_override=0.0 으로 deterministic 추론. 가중치 변동 없음.

사용:
  python3 bench_boss_baseline.py                              # 모든 시나리오 30판
  python3 bench_boss_baseline.py --games 50                   # 50판
  python3 bench_boss_baseline.py --scenarios easy medium      # 특정 시나리오만
  python3 bench_boss_baseline.py --json results.json          # 결과 JSON 저장
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Callable

_BR_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_BR_ROOT))
sys.path.insert(0, str(_BR_ROOT.parent))

from core.bot_interface import BotInterface
from core.engine import GameEngine
from src.arena.server.boss.config import boss_battle_config

from bots.boss.rl_boss_bot import RLBossBot
from bots.boss.rule_boss_bot import RuleBossEasyBot, RuleBossMediumBot

# ---------------------------------------------------------------------------
# 추론 전용 모드: 학습/저장 비활성화
# RLBossBot은 평소 매 step `_learn()` + 매 에피소드 `save_weights()` 호출하므로,
# 벤치마크 중에도 가중치가 mutate된다 (디스크에도 저장됨).
# 깨끗한 baseline 측정을 위해 모듈 레벨에서 monkey-patch.
# ---------------------------------------------------------------------------
RLBossBot._learn       = lambda self: None
RLBossBot.save_weights = lambda self, path=None: None
from bots.boss.claude_bot import ClaudeBot
from bots.battle_royale.herbivore import HerbivoreBot
from bots.battle_royale.camper import CamperBot
from bots.battle_royale.mad_dog import MadDogBot
from bots.battle_royale.sample_user_bots import (
    DuelistBot, OptimizerBot, AdaptorBot, ShieldTankBot, CounterMinerBot,
)

BOSS_ID = "AI_보스"

# ---------------------------------------------------------------------------
# 시나리오 정의: 각 시나리오는 (boss_id 제외) 상대 N-1명을 만드는 팩토리.
# 4봇/5봇 게임 혼용 — 보스전 정식 모드(유저 1~3 + 보스 1)와 균등 비교(5봇) 둘 다 측정.
# ---------------------------------------------------------------------------

def _opp_easy(seed: int) -> list[BotInterface]:
    return [RuleBossEasyBot(bot_id=f"Easy_{i}", seed=seed + i) for i in range(4)]

def _opp_medium(seed: int) -> list[BotInterface]:
    return [RuleBossMediumBot(bot_id=f"Med_{i}", seed=seed + i) for i in range(4)]

def _opp_claude_mix(seed: int) -> list[BotInterface]:
    """5봇: 더 빡센 setup. Camper(점수형) 추가로 보스 입장 가장 어려움."""
    return [
        ClaudeBot     (bot_id="Claude",  seed=seed),
        HerbivoreBot  (bot_id="초식_0",  seed=seed + 1),
        HerbivoreBot  (bot_id="초식_1",  seed=seed + 2),
        CamperBot     (bot_id="존버_0",  seed=seed + 3),
    ]

def _opp_claude_4bot(seed: int) -> list[BotInterface]:
    """4봇: 문서 기록(27%) 재현 시도. Boss + Claude + Herb×2."""
    return [
        ClaudeBot     (bot_id="Claude",   seed=seed),
        HerbivoreBot  (bot_id="초식_0",   seed=seed + 1),
        HerbivoreBot  (bot_id="초식_1",   seed=seed + 2),
    ]

def _opp_claude2_4bot(seed: int) -> list[BotInterface]:
    """4봇: 또 다른 해석 — ClaudeBot×2 + Herb 1명."""
    return [
        ClaudeBot     (bot_id="Claude_0", seed=seed),
        ClaudeBot     (bot_id="Claude_1", seed=seed + 1),
        HerbivoreBot  (bot_id="초식_0",   seed=seed + 2),
    ]

def _opp_boss_mode_solo(seed: int) -> list[BotInterface]:
    """실제 보스전 모드 (유저 1 + 보스 1) — 2봇 게임. Claude 단독 도전."""
    return [
        ClaudeBot     (bot_id="Claude",   seed=seed),
    ]

def _opp_boss_mode_trio(seed: int) -> list[BotInterface]:
    """실제 보스전 모드 (유저 3 + 보스 1) — 4봇 게임. 운영 최대 규모."""
    return [
        ClaudeBot     (bot_id="Claude",   seed=seed),
        ClaudeBot     (bot_id="Claude_2", seed=seed + 10),
        ClaudeBot     (bot_id="Claude_3", seed=seed + 20),
    ]

def _opp_sample_mix(seed: int) -> list[BotInterface]:
    return [
        DuelistBot    (bot_id="결투사",   seed=seed),
        OptimizerBot  (bot_id="최적화",   seed=seed + 1),
        AdaptorBot    (bot_id="적응형",   seed=seed + 2),
        ShieldTankBot (bot_id="탱커",     seed=seed + 3),
    ]

def _opp_counter_mix(seed: int) -> list[BotInterface]:
    """CounterMiner 1명 + 다양성 3명. 보스의 mining 편향 직접 펀치."""
    return [
        CounterMinerBot (bot_id="카운터",   seed=seed),
        OptimizerBot    (bot_id="최적화",   seed=seed + 1),
        HerbivoreBot    (bot_id="초식",     seed=seed + 2),
        ClaudeBot       (bot_id="Claude",   seed=seed + 3),
    ]

def _opp_counter_only(seed: int) -> list[BotInterface]:
    """CounterMiner × 4 — 가장 빡센 시나리오. M2 검증용."""
    return [
        CounterMinerBot(bot_id=f"카운터_{i}", seed=seed + i)
        for i in range(4)
    ]

SCENARIOS: dict[str, Callable[[int], list[BotInterface]]] = {
    "easy":             _opp_easy,
    "medium":           _opp_medium,
    "claude_mix":       _opp_claude_mix,
    "claude_4bot":      _opp_claude_4bot,
    "claude2_4bot":     _opp_claude2_4bot,
    "boss_mode_solo":   _opp_boss_mode_solo,
    "boss_mode_trio":   _opp_boss_mode_trio,
    "sample_mix":       _opp_sample_mix,
    "counter_mix":      _opp_counter_mix,
    "counter_only":     _opp_counter_only,
}

SEED_BASES = {
    "easy":             10_000,
    "medium":           20_000,
    "claude_mix":       30_000,
    "claude_4bot":      31_000,
    "claude2_4bot":     32_000,
    "boss_mode_solo":   33_000,
    "boss_mode_trio":   34_000,
    "sample_mix":       40_000,
    "counter_mix":      50_000,
    "counter_only":     51_000,
}


# ---------------------------------------------------------------------------
# 한 시나리오 실행
# ---------------------------------------------------------------------------

def _run_scenario(name: str, n_games: int, weights_path: Path | None) -> dict:
    factory  = SCENARIOS[name]
    seed_base = SEED_BASES[name]
    cfg = boss_battle_config()

    # 보스는 한 인스턴스를 재사용 (가중치 변동 없음 — epsilon=0)
    boss = RLBossBot(
        bot_id=BOSS_ID,
        seed=seed_base + 99,
        weights_path=weights_path,
        epsilon_override=0.0,
    )

    ranks, scores, kills, surv = [], [], [], []
    n_bots_in_game = 1 + len(factory(seed_base))
    t_start = time.perf_counter()

    for g in range(n_games):
        seed = seed_base + g
        boss.reset_for_episode()

        opponents = factory(seed)
        bots: list[BotInterface] = [boss] + opponents

        engine = GameEngine(bots, config=cfg, seed=seed)
        result = engine.run_full_game()

        for e in result.rankings:
            if e.get("id") == BOSS_ID:
                ranks .append(int(e.get("rank", n_bots_in_game)))
                scores.append(float(e.get("final_score", 0.0)))
                kills .append(int(e.get("kills", 0)))
                surv  .append(int(e.get("survival_ticks", 0)))
                break

    elapsed = time.perf_counter() - t_start
    n = len(ranks)
    wins     = sum(1 for r in ranks if r == 1)
    top2     = sum(1 for r in ranks if r <= 2)
    avg_rank = sum(ranks)  / n if n else 0
    avg_score= sum(scores) / n if n else 0
    avg_kill = sum(kills)  / n if n else 0
    avg_surv = sum(surv)   / n if n else 0

    return {
        "scenario":  name,
        "n_bots":    n_bots_in_game,
        "random_win_rate": 1.0 / n_bots_in_game,
        "n_games":   n,
        "wins":      wins,
        "win_rate":  wins / n if n else 0,
        "top2":      top2,
        "top2_rate": top2 / n if n else 0,
        "avg_rank":  avg_rank,
        "avg_score": avg_score,
        "avg_kills": avg_kill,
        "avg_survival_ticks": avg_surv,
        "elapsed_sec": elapsed,
        "ranks":     ranks,
    }


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------

def _print_summary(results: list[dict]) -> None:
    print()
    print("=" * 92)
    print(f"  {'시나리오':<16}{'봇수':>4}{'판수':>5}{'승률':>9}{'(rand)':>8}{'Top-2':>8}{'평균순위':>10}{'평균점수':>10}{'평균킬':>8}{'시간(s)':>10}")
    print("-" * 92)
    for r in results:
        print(
            f"  {r['scenario']:<16}"
            f"{r['n_bots']:>4}"
            f"{r['n_games']:>5}"
            f"{r['win_rate']*100:>8.1f}%"
            f"{r['random_win_rate']*100:>7.0f}%"
            f"{r['top2_rate']*100:>7.1f}%"
            f"{r['avg_rank']:>10.2f}"
            f"{r['avg_score']:>10.1f}"
            f"{r['avg_kills']:>8.2f}"
            f"{r['elapsed_sec']:>10.1f}"
        )
    print("=" * 92)
    print()


def _print_distribution(results: list[dict]) -> None:
    """순위 분포 히스토그램 (시나리오별)."""
    for r in results:
        nb = r["n_bots"]
        dist = [0] * nb
        for rank in r["ranks"]:
            if 1 <= rank <= nb:
                dist[rank - 1] += 1
        n = r["n_games"]
        bars = " ".join(
            f"{rank+1}위:{cnt:>3}({cnt/n*100:>4.0f}%)"
            for rank, cnt in enumerate(dist)
        )
        print(f"  [{r['scenario']:<16}] (봇{nb}) {bars}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", nargs="+", default=list(SCENARIOS.keys()),
                        choices=list(SCENARIOS.keys()))
    parser.add_argument("--games", type=int, default=30,
                        help="시나리오당 게임 수 (default: 30)")
    parser.add_argument("--weights", type=str, default=None,
                        help="가중치 파일 경로 (default: bots/boss/trained_weights.json)")
    parser.add_argument("--json", type=str, default=None,
                        help="결과 JSON 저장 경로")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    weights_path = Path(args.weights) if args.weights else None

    print("=" * 78)
    print(f"  보스봇 baseline 벤치마크  |  시나리오 {len(args.scenarios)}개 × {args.games}판")
    print(f"  가중치: {weights_path or '기본 (trained_weights.json)'}")
    print(f"  보스 epsilon: 0.0 (deterministic, 학습 비활성)")
    print("=" * 78)

    results = []
    for name in args.scenarios:
        if not args.quiet:
            print(f"  [{name}] 진행 중...", flush=True)
        r = _run_scenario(name, args.games, weights_path)
        results.append(r)
        if not args.quiet:
            print(f"    → 승률 {r['win_rate']*100:.1f}% (top-2 {r['top2_rate']*100:.1f}%)  "
                  f"평균순위 {r['avg_rank']:.2f}  {r['elapsed_sec']:.1f}s")

    _print_summary(results)
    if not args.quiet:
        _print_distribution(results)

    if args.json:
        # ranks 리스트는 용량 절약을 위해 분포만 저장
        summary = []
        for r in results:
            d = {k: v for k, v in r.items() if k != "ranks"}
            nb = r["n_bots"]
            dist = [0] * nb
            for rank in r["ranks"]:
                if 1 <= rank <= nb:
                    dist[rank - 1] += 1
            d["rank_distribution"] = dist
            summary.append(d)
        Path(args.json).write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"  JSON 저장: {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
