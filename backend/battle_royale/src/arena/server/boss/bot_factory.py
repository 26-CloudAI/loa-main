"""보스봇 생성 팩토리 + RL 싱글톤 동시성 락.

app.py의 `_create_boss_bot`을 그대로 이동한 모듈.
난이도별 봇 클래스 분기 + RL 보스봇 싱글톤 캐시 + GCS 가중치 다운로드까지
한 함수에서 책임진다.

`BOSS_BOT_LOCK`은 lifespan의 hot-reload 루프와 공유되므로 외부에 노출한다.
"""

from __future__ import annotations

import logging
import time
import threading
from typing import Optional

from core.bot_interface import BotInterface

logger = logging.getLogger(__name__)

# RLBossBot 싱글톤 보호용 락. create_boss_bot은 FastAPI 워커 스레드 풀에서
# 동시에 호출될 수 있으며, reset_for_episode 도중에 다른 요청이 같은 인스턴스를
# 사용하면 _prev_state 등이 오염된다. 락으로 직렬화한다.
BOSS_BOT_LOCK = threading.Lock()


def create_boss_bot(
    existing_ids: set[str],
    difficulty: str = "상",
    rl_singleton_state: Optional[dict] = None,
) -> BotInterface:
    """
    보스전용 봇 생성. 난이도에 따라 봇 종류가 다름.
      하 → RuleBossEasyBot  (룰베이스, 채굴·생존 중심)
      중 → RuleBossMediumBot (룰베이스, 채굴+전투 균형)
      상 → RLBossBot         (강화학습, GCS 가중치 사용)

    rl_singleton_state: 주어지면 "rl_boss_bot" 키에 RLBossBot 인스턴스를
    캐싱하여 보스전마다 동일 인스턴스를 재사용한다. 리플레이 버퍼/가중치/
    epsilon이 게임 사이에 유지되어 프로덕션 학습이 가능해진다.
    """
    bot_id = "AI_보스"
    existing_ids.add(bot_id)

    if difficulty == "하":
        from bots.boss.rule_boss_bot import RuleBossEasyBot
        return RuleBossEasyBot(bot_id=bot_id, seed=int(time.time()) % 65536)

    if difficulty == "중":
        from bots.boss.rule_boss_bot import RuleBossMediumBot
        return RuleBossMediumBot(bot_id=bot_id, seed=int(time.time()) % 65536)

    # 상 (기본값): RL 보스봇 + GCS 가중치 — 싱글톤 재사용
    # 학습은 PyTorch(.pt) 포맷, 서빙은 PyTorch가 있으면 동일 포맷을 사용해
    # 학습 결과가 즉시 반영되도록 한다. PyTorch가 없으면 numpy 버전으로 폴백
    # (단, .pt 가중치는 로드되지 않으므로 무작위 초기화 상태로 동작한다).
    from ... import gcs_weights

    # 동시 보스전 요청이 같은 인스턴스를 reset_for_episode하는 경쟁 상태를 방지.
    # 락 내부에서 싱글톤 조회/reset/생성/저장을 모두 직렬화한다.
    with BOSS_BOT_LOCK:
        if rl_singleton_state is not None:
            cached = rl_singleton_state.get("rl_boss_bot")
            if cached is not None:
                try:
                    cached.reset_for_episode()
                    return cached
                except Exception:
                    logger.exception(
                        "RL 보스봇 싱글톤 reset 실패 — 새 인스턴스 생성"
                    )

        cache = gcs_weights.local_cache_path()
        # 캐시가 없고 GCS가 활성화된 경우 서버 시작 시 다운로드 실패를 재시도
        if not cache.exists() and gcs_weights.enabled():
            logger.info("보스봇 가중치 캐시 없음 — GCS 재다운로드 시도")
            gcs_weights.download()
        weights_path = cache if cache.exists() else None

        # PyTorch 사용 가능 + 가중치가 .pt면 Torch 봇을, 아니면 numpy 봇을 사용.
        use_torch = False
        if weights_path is not None and str(weights_path).endswith(".pt"):
            try:
                import torch  # noqa: F401
                use_torch = True
            except ImportError:
                logger.warning(
                    "PyTorch 가중치(.pt)가 다운로드됐지만 torch 미설치 — "
                    "numpy 보스봇으로 폴백 (학습 가중치 반영 안 됨)"
                )

        if use_torch:
            from bots.boss.rl_boss_bot_torch import RLBossBotTorch
            bot = RLBossBotTorch(
                bot_id=bot_id, seed=0, weights_path=weights_path, device="cpu"
            )
        else:
            from bots.boss.rl_boss_bot import RLBossBot
            bot = RLBossBot(bot_id=bot_id, seed=0, weights_path=weights_path)

        if rl_singleton_state is not None:
            rl_singleton_state["rl_boss_bot"] = bot
            logger.info(
                "RL 보스봇 싱글톤 인스턴스 생성 (%s) — 이후 보스전에서 재사용",
                type(bot).__name__,
            )

        return bot
