"""
RLBossBot 실시간 학습 서버
===========================

WebSocket으로 학습 진행 상황을 스트리밍하는 FastAPI 서버.
브라우저에서 실시간으로 보스봇 학습을 시각화할 수 있다.

사용법:
    python train_boss_bot_server.py
    python train_boss_bot_server.py --episodes 200 --bots 5 --port 8765
    python train_boss_bot_server.py --episodes 500 --tick-delay 0.02
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path

_BR_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_BR_ROOT))
sys.path.insert(0, str(_BR_ROOT.parent))  # backend/ (core 검색용)

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

from core.config import DEFAULT_CONFIG
from core.engine import GameEngine
from core.vision import build_leaderboard
from bots.battle_royale.herbivore import HerbivoreBot
from bots.battle_royale.mad_dog import MadDogBot
from bots.battle_royale.camper import CamperBot
from bots.boss.rl_boss_bot import RLBossBot

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

BOSS_BOT_ID   = "boss_rl"
OPPONENTS = [
    (HerbivoreBot, "초식"),
    (MadDogBot,    "미친개"),
    (CamperBot,    "존버"),
]
WEIGHTS_PATH  = Path(__file__).resolve().parent.parent.parent / "bots" / "boss" / "trained_weights.json"
SAVE_INTERVAL = 10  # N 에피소드마다 자동 저장
VIEWER_HTML = Path(__file__).resolve().parent.parent / "tools" / "train_boss_bot_viewer.html"

# ---------------------------------------------------------------------------
# 앱
# ---------------------------------------------------------------------------

app = FastAPI(title="RLBossBot 학습 서버")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 학습 설정 (argparse 결과를 저장)
_config: dict = {}


# ---------------------------------------------------------------------------
# WebSocket 학습 스트리머
# ---------------------------------------------------------------------------

async def _send(ws: WebSocket, msg: dict) -> None:
    await ws.send_text(json.dumps(msg, ensure_ascii=False))


def _build_tick_snapshot(engine: GameEngine) -> dict:
    """현재 엔진 상태를 클라이언트가 쓸 수 있는 dict로 변환."""
    bots_data = []
    for bot in engine.bots.values():
        bots_data.append({
            "id": bot.id,
            "x": bot.position.x,
            "y": bot.position.y,
            "energy": bot.energy,
            "score": bot.score,
            "alive": bot.alive,
            "shield_active": bot.shield_active,
        })

    minerals_data = []
    for x, y, rare in engine.grid.get_all_mineral_positions():
        minerals_data.append({"x": x, "y": y, "rare": rare})

    lb = build_leaderboard(engine.bots, engine.config)
    zone = engine.zone.bounds  # (minX, minY, maxX, maxY)

    return {
        "type": "tick",
        "tick": engine.tick,
        "bots": bots_data,
        "minerals": minerals_data,
        "zone_bounds": list(zone),
        "alive_count": sum(1 for b in engine.bots.values() if b.alive),
        "leaderboard": lb,
    }


async def run_training(ws: WebSocket, n_episodes: int, n_bots: int,
                       base_seed: int, tick_delay: float) -> None:
    """학습 루프를 실행하면서 WebSocket으로 진행 상황을 전송한다."""

    rng = random.Random(base_seed)

    await _send(ws, {
        "type": "training_start",
        "episodes": n_episodes,
        "bots": n_bots,
        "tick_delay": tick_delay,
    })

    # ── 보스봇 단일 인스턴스 (에피소드 간 가중치·버퍼·epsilon 유지) ──
    boss_bot = RLBossBot(
        bot_id=BOSS_BOT_ID,
        seed=rng.randint(0, 10_000),
        # weights_path 기본값으로 자동 로드 → 이전 학습 이어받기
    )

    rank_history: list[int]   = []
    score_history: list[float] = []
    best_avg_rank = float("inf")
    t_start = time.time()

    for ep in range(1, n_episodes + 1):
        ep_seed    = rng.randint(0, 1_000_000)
        n_opponents = n_bots - 1

        # ── 에피소드 시작: 틱 상태만 초기화 (가중치·버퍼·epsilon 유지) ──
        boss_bot.reset_for_episode()

        opponents = []
        for i in range(n_opponents):
            cls, label = rng.choice(OPPONENTS)
            opponents.append(cls(bot_id=f"{label}_{i:02d}", seed=ep_seed + i))

        all_bots = [boss_bot] + opponents
        engine   = GameEngine(all_bots, config=DEFAULT_CONFIG, seed=ep_seed)

        await _send(ws, {
            "type":    "episode_start",
            "episode": ep,
            "total":   n_episodes,
            "epsilon": round(boss_bot._epsilon, 4),
            "steps":   boss_bot._step_count,
            "bot_ids": [b.bot_id for b in all_bots],
        })

        # 틱 단위로 실행
        tick_count = 0
        while not engine.game_over:
            engine.process_tick()
            tick_count += 1

            send_now = (tick_delay > 0) or (tick_count % 10 == 0)
            if send_now:
                try:
                    await _send(ws, _build_tick_snapshot(engine))
                except Exception:
                    return

            if tick_delay > 0:
                await asyncio.sleep(tick_delay)
            else:
                await asyncio.sleep(0)

        # ── 에피소드 결과 수집 ──
        result   = engine.game_result
        rankings = result.rankings if result else []
        rank, score, survival = n_bots, 0.0, 0
        for entry in rankings:
            if entry.get("id") == BOSS_BOT_ID:
                rank     = entry["rank"]
                score    = entry.get("final_score", 0.0)
                survival = entry.get("survival_ticks", 0)
                break

        # ── 에피소드 종료 보상 + epsilon 감쇠 ──
        boss_bot.on_episode_done(rank, n_bots)

        rank_history.append(rank)
        score_history.append(score)

        window    = min(100, ep)
        avg_rank  = sum(rank_history[-window:]) / window
        avg_score = sum(score_history[-window:]) / window

        if avg_rank < best_avg_rank:
            best_avg_rank = avg_rank

        await _send(ws, {
            "type":     "episode_end",
            "episode":  ep,
            "total":    n_episodes,
            "rank":     rank,
            "n_bots":   n_bots,
            "score":    score,
            "survival": survival,
            "avg_rank":  round(avg_rank, 3),
            "avg_score": round(avg_score, 1),
            "epsilon":   round(boss_bot._epsilon, 4),
            "steps":     boss_bot._step_count,
            "buffer":    len(boss_bot._buffer),
            "elapsed":   round(time.time() - t_start, 1),
            "reason":    result.reason.value if result else "unknown",
        })

        # ── 주기적 자동 저장 (SAVE_INTERVAL 에피소드마다) ──
        if ep % SAVE_INTERVAL == 0:
            boss_bot.save_weights(WEIGHTS_PATH)

    # ── 훈련 완료 — 최종 저장 ──
    boss_bot.save_weights(WEIGHTS_PATH)

    total_avg_rank = sum(rank_history) / len(rank_history)
    total_avg_score = sum(score_history) / len(score_history)

    await _send(ws, {
        "type":           "training_complete",
        "total_episodes": n_episodes,
        "total_avg_rank": round(total_avg_rank, 3),
        "total_avg_score": round(total_avg_score, 1),
        "best_avg_rank":  round(best_avg_rank, 3),
        "total_steps":    boss_bot._step_count,
        "final_epsilon":  round(boss_bot._epsilon, 4),
        "buffer_size":    len(boss_bot._buffer),
        "elapsed":        round(time.time() - t_start, 1),
        "weights_saved":  str(WEIGHTS_PATH),
    })


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root():
    if VIEWER_HTML.exists():
        return HTMLResponse(content=VIEWER_HTML.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>train_boss_bot_viewer.html 파일이 없습니다.</h1>")


@app.get("/config")
async def get_config():
    return _config


@app.websocket("/ws/train")
async def ws_train(
    ws: WebSocket,
    episodes: Optional[int] = Query(default=None),
    bots: Optional[int] = Query(default=None),
    seed: Optional[int] = Query(default=None),
    tick_delay: Optional[float] = Query(default=None),
):
    await ws.accept()
    try:
        await run_training(
            ws,
            n_episodes=episodes if episodes is not None else _config.get("episodes", 100),
            n_bots=bots if bots is not None else _config.get("bots", 5),
            base_seed=seed if seed is not None else _config.get("seed", 42),
            tick_delay=tick_delay if tick_delay is not None else _config.get("tick_delay", 0.0),
        )
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await _send(ws, {"type": "error", "message": str(e)})
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RLBossBot 실시간 학습 서버",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--episodes", "-e", type=int, default=100, help="총 훈련 에피소드 수")
    parser.add_argument("--bots", "-b", type=int, default=5, help="에피소드당 총 봇 수")
    parser.add_argument("--seed", "-s", type=int, default=42, help="랜덤 시드")
    parser.add_argument("--tick-delay", type=float, default=0.0,
                        help="틱 간 딜레이(초). 0=빠른 학습, 0.05=느린 시각화")
    parser.add_argument("--port", type=int, default=8765, help="서버 포트")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="서버 호스트")
    return parser.parse_args()


if __name__ == "__main__":
    import uvicorn

    args = _parse_args()
    if args.bots < 2:
        print("오류: --bots 는 최소 2 이상이어야 합니다.", file=sys.stderr)
        sys.exit(1)

    _config.update({
        "episodes": args.episodes,
        "bots": args.bots,
        "seed": args.seed,
        "tick_delay": args.tick_delay,
    })

    print("=" * 55)
    print("  RLBossBot 실시간 학습 서버")
    print(f"  브라우저: http://{args.host}:{args.port}")
    print(f"  에피소드: {args.episodes} | 봇 수: {args.bots}")
    print(f"  틱 딜레이: {args.tick_delay}s")
    print("=" * 55)

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
