"""
Isolated bot execution via multiprocessing (spawn context).

Security layers applied in each child process:
  1. os.environ.clear()   — remove all inherited secrets
  2. resource limits      — CPU time, address space, file size, process count
  3. signal.SIGALRM       — hard timeout inside the child
  4. filtered __builtins__ — dangerous built-ins removed from exec namespace
  5. gVisor (at Pod level) — syscall filtering (outside this file)

spawn context is used (not fork) for gVisor compatibility and uvicorn thread safety.
Each request spawns a fresh process. Consider a process pool if latency is a concern.
"""

from __future__ import annotations

import builtins as _builtins_module
import multiprocessing
import os
import resource
import signal
from typing import Any, Tuple

# Spawn context: fresh Python interpreter per child (gVisor-compatible)
_mp_ctx = multiprocessing.get_context("spawn")

_BLOCKED_BUILTINS = frozenset([
    "open", "exec", "eval", "compile", "__import__", "input", "breakpoint",
    "__loader__", "__spec__",
    # Attribute access helpers — aliasable sandbox escapes
    "getattr", "setattr", "delattr", "hasattr",
])

# Computed once at import time; child process re-computes from its own builtins module
SAFE_BUILTINS: dict = {
    k: v for k, v in vars(_builtins_module).items() if k not in _BLOCKED_BUILTINS
}

BATTLEROYALE_VALID = frozenset([
    "STAY",
    "MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT",
    "MOVE_UP_LEFT", "MOVE_UP_RIGHT", "MOVE_DOWN_LEFT", "MOVE_DOWN_RIGHT",
    "MINE",
    "ATTACK_UP", "ATTACK_DOWN", "ATTACK_LEFT", "ATTACK_RIGHT",
    "ATTACK_UP_LEFT", "ATTACK_UP_RIGHT", "ATTACK_DOWN_LEFT", "ATTACK_DOWN_RIGHT",
    "SHIELD",
])

STOCKS_VALID = frozenset(["BUY", "SELL", "SHORT", "COVER", "INQUIRY", "HOLD"])


def _child_entry(
    source_code: str,
    state: dict,
    result_queue: multiprocessing.SimpleQueue,
    action_timeout_sec: float,
) -> None:
    """Runs inside an isolated child process. Never called directly in the parent."""
    # 1. Wipe inherited environment (secrets, credentials)
    os.environ.clear()

    # 2. Resource limits (best-effort; gVisor may restrict some setrlimit calls)
    _limits = [
        (resource.RLIMIT_CPU,   (1, 1)),
        (resource.RLIMIT_AS,    (256 * 1024 * 1024, 256 * 1024 * 1024)),
        (resource.RLIMIT_FSIZE, (0, 0)),
        (resource.RLIMIT_NPROC, (0, 0)),
    ]
    for limit_type, (soft, hard) in _limits:
        try:
            resource.setrlimit(limit_type, (soft, hard))
        except Exception:
            pass

    # 3. Signal-based timeout (fires after ceil(action_timeout_sec), minimum 1s)
    def _on_alarm(signum, frame):  # noqa: ARG001
        raise TimeoutError("action timeout")

    try:
        signal.signal(signal.SIGALRM, _on_alarm)
        signal.alarm(max(1, int(action_timeout_sec) + 1))
    except Exception:
        pass

    # 4. Compile and execute user code in a restricted namespace
    # Compilation happens in the child to avoid pickling code objects (Python 3.14+)
    try:
        compiled = compile(source_code, "<bot>", "exec")
        ns: dict = {"__builtins__": SAFE_BUILTINS}
        exec(compiled, ns)  # noqa: S102
        fn = ns.get("action")
        if not callable(fn):
            result_queue.put(("error", "no callable action() function defined"))
            return
        result = fn(state)
        result_queue.put(("ok", result))
    except Exception as exc:
        result_queue.put(("error", str(exc)))


def run(
    source_code: str,
    state: dict,
    mode: str,
    action_timeout_sec: float,
) -> Tuple[bool, Any, str]:
    """
    Spawn a child process, run user bot code, and return (ok, action, error).
    Always returns a valid fallback action on failure — never raises.

    Parent join timeout = action_timeout_sec + 5.0 to absorb spawn overhead.
    The game server's HTTP client timeout handles user-facing latency separately.
    """
    default: Any = "STAY" if mode == "battleroyale" else {"action": "HOLD"}
    process_timeout = action_timeout_sec + 5.0

    q: multiprocessing.SimpleQueue = _mp_ctx.SimpleQueue()
    proc = _mp_ctx.Process(
        target=_child_entry,
        args=(source_code, state, q, action_timeout_sec),
        daemon=True,
    )

    try:
        proc.start()
        proc.join(timeout=process_timeout)

        if proc.is_alive():
            proc.kill()
            proc.join(timeout=1.0)
            return False, default, "timeout"

        if proc.exitcode != 0:
            return False, default, f"process exited with code {proc.exitcode}"

        if q.empty():
            return False, default, "no result received from child process"
        status, value = q.get()

        if status != "ok":
            return False, default, str(value)

        validated = _validate(value, mode, default)
        return True, validated, ""

    except Exception as exc:
        return False, default, str(exc)
    finally:
        if proc.is_alive():
            proc.kill()


def _validate(raw: Any, mode: str, default: Any) -> Any:
    if mode == "battleroyale":
        if isinstance(raw, str) and raw in BATTLEROYALE_VALID:
            return raw
        return default
    else:  # stocks
        if not isinstance(raw, dict):
            return default
        if raw.get("action") not in STOCKS_VALID:
            return default
        return raw
