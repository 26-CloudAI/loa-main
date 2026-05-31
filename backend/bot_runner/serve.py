"""Programmatic uvicorn launcher for the bot-runner.

Why not the `uvicorn main:app` CLI?
  Under gVisor, every /run forks a child (via the forkserver) to execute the bot.
  Measured per-call latency on the same Pod:
    - CLI  `uvicorn main:app`     → ~214ms
    - programmatic `uvicorn.run(app)` → ~60ms
  i.e. the CLI launch adds ~150ms of pure per-request overhead. BR2 is lock-step
  (the browser waits for the server's bot decision each tick), so this latency
  directly throttles the game. Launching uvicorn programmatically (passing the app
  object, not an import string) avoids that overhead.

We also warm the forkserver before serving so the first real request isn't slow.
"""
import os

import executor
import main
import uvicorn

if __name__ == "__main__":
    executor.warmup()  # spin up the forkserver before the first request
    uvicorn.run(
        main.app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8001")),
        log_level="info",
    )
