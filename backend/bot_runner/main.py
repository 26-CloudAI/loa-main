from __future__ import annotations

import asyncio
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI

import cache
import executor
import policy
from schemas import RunRequest, RunResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="BotRunner")

ACTION_TIMEOUT_SEC = float(os.environ.get("BOT_ACTION_TIMEOUT_SEC", "0.1"))
_WORKERS = int(os.environ.get("BOT_RUNNER_WORKERS", "4"))
_thread_pool = ThreadPoolExecutor(max_workers=_WORKERS)

# Backpressure: cap in-flight executions at the worker count and shed excess
# load with an immediate fallback. Without this, a flood of slow bots queues
# unboundedly in the thread pool, backlogging unrelated games long after their
# HTTP callers have timed out.
_inflight = threading.BoundedSemaphore(_WORKERS)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/livez")
def livez() -> dict:
    return {"status": "alive"}


@app.post("/run", response_model=RunResponse)
async def run_bot(req: RunRequest) -> RunResponse:
    if not _inflight.acquire(blocking=False):
        logger.warning("runner saturated, shedding bot_id=%s", req.bot_id)
        return RunResponse(ok=False, action=_default_action(req.mode), error="runner saturated")
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_thread_pool, _handle_run, req)
    finally:
        _inflight.release()


def _handle_run(req: RunRequest) -> RunResponse:
    default = _default_action(req.mode)

    # Cache stores validated source code strings (policy-checked)
    source: str | None = cache.get(req.code_hash)

    if source is None:
        if req.code is None:
            return RunResponse(ok=False, action=default, error="cache miss and no code provided")

        try:
            policy.check(req.code)
        except ValueError as exc:
            logger.warning("policy violation bot_id=%s: %s", req.bot_id, exc)
            return RunResponse(ok=False, action=default, error=str(exc))

        # Validate syntax before caching
        try:
            compile(req.code, "<bot>", "exec")
        except SyntaxError as exc:
            return RunResponse(ok=False, action=default, error=f"syntax error: {exc}")

        cache.put(req.code_hash, req.code)
        source = req.code

    ok, action, error = executor.run(source, req.state, req.mode, ACTION_TIMEOUT_SEC, req.phase)

    if not ok:
        logger.info("bot error bot_id=%s mode=%s: %s", req.bot_id, req.mode, error)

    return RunResponse(ok=ok, action=action, error=error or None)


def _default_action(mode: str) -> object:
    return executor._default_for(mode)
