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

# Allowlist (not blacklist) of builtins exposed to untrusted bot code.
# Anything not listed is unavailable: open/exec/eval/compile/__import__,
# getattr/setattr/delattr/hasattr, globals/locals/vars/dir, input/breakpoint,
# and — critically — the site-injected helper objects help/license/credits/
# copyright/exit/quit, which can read arbitrary files (e.g. str(license)
# opens license._Printer__filenames) without ever calling open().
# A blacklist could never enumerate every such capability-bearing object.
_ALLOWED_BUILTINS = frozenset([
    # constants
    "None", "True", "False", "NotImplemented", "Ellipsis", "__debug__",
    # class/def machinery (needed when bot code defines its own classes)
    "__build_class__",
    # safe value types / constructors
    "bool", "bytearray", "bytes", "complex", "dict", "float", "frozenset",
    "int", "list", "object", "set", "slice", "str", "tuple", "type", "range",
    # safe pure functions
    "abs", "all", "any", "ascii", "bin", "callable", "chr", "divmod",
    "enumerate", "filter", "format", "hash", "hex", "id", "isinstance",
    "issubclass", "iter", "len", "map", "max", "min", "next", "oct", "ord",
    "pow", "print", "repr", "reversed", "round", "sorted", "sum", "zip",
    # class-definition helpers commonly used by user bots
    "super", "staticmethod", "classmethod", "property",
])


def _build_safe_builtins() -> dict:
    src = vars(_builtins_module)
    safe = {name: src[name] for name in _ALLOWED_BUILTINS if name in src}
    # Exception classes are harmless and required for try/except in bot code.
    for name, val in src.items():
        if isinstance(val, type) and issubclass(val, BaseException):
            safe[name] = val
    return safe


# Computed once at import; child re-imports this module under spawn and recomputes.
SAFE_BUILTINS: dict = _build_safe_builtins()

# Parent join = action timeout + grace (covers spawn/import overhead). Kept
# tight so an abandoned request frees its worker quickly instead of lingering
# for seconds after the game server's HTTP call has already timed out.
_PROCESS_GRACE_SEC = float(os.environ.get("BOT_PROCESS_GRACE_SEC", "1.0"))

# Bounds on stocks action output, applied before the dict crosses the
# BotRunner→game-server boundary (prevents oversized-output DoS).
_MAX_SYMBOL_LEN = 64
_MAX_QUANTITY = 10 ** 9

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
    mode: str,
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

    # 3. Signal-based timeout. setitimer honours sub-second values, unlike
    #    signal.alarm() which only takes whole seconds and would round a
    #    0.1s budget up to 1s — letting a slow bot run long after the game
    #    server's HTTP call (0.5s) already gave up.
    def _on_alarm(signum, frame):  # noqa: ARG001
        raise TimeoutError("action timeout")

    try:
        signal.signal(signal.SIGALRM, _on_alarm)
        signal.setitimer(signal.ITIMER_REAL, max(0.01, action_timeout_sec))
    except Exception:
        pass

    # 4. Compile and execute user code in a restricted namespace
    # Compilation happens in the child to avoid pickling code objects (Python 3.14+)
    try:
        compiled = compile(source_code, "<bot>", "exec")
        # __name__ is required for class definitions (__module__ resolution).
        ns: dict = {"__builtins__": SAFE_BUILTINS, "__name__": "__bot__"}
        exec(compiled, ns)  # noqa: S102
        fn = ns.get("action")
        if not callable(fn):
            result_queue.put(("error", "no callable action() function defined"))
            return
        result = fn(state)
        # Validate/normalize INSIDE the child, before the value crosses the
        # IPC boundary. Sending the raw bot output risks (a) a pipe-buffer
        # deadlock when it exceeds ~64KB and (b) serializing attacker-sized
        # payloads every tick. Only the bounded, validated action is sent.
        default = "STAY" if mode == "battleroyale" else {"action": "HOLD"}
        result_queue.put(("ok", _validate(result, mode, default)))
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

    Parent join timeout = action_timeout_sec + _PROCESS_GRACE_SEC (spawn/import
    overhead). Kept tight so an abandoned request frees its worker quickly
    rather than lingering for seconds after the game server's HTTP call timed out.
    """
    default: Any = "STAY" if mode == "battleroyale" else {"action": "HOLD"}
    process_timeout = action_timeout_sec + _PROCESS_GRACE_SEC

    q: multiprocessing.SimpleQueue = _mp_ctx.SimpleQueue()
    proc = _mp_ctx.Process(
        target=_child_entry,
        args=(source_code, state, q, action_timeout_sec, mode),
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

        # value was already validated/normalized inside the child.
        return True, value, ""

    except Exception as exc:
        return False, default, str(exc)
    finally:
        if proc.is_alive():
            proc.kill()


def _validate(raw: Any, mode: str, default: Any) -> Any:
    if mode == "battleroyale":
        # Length guard first: avoids hashing a multi-MB string for set membership.
        if isinstance(raw, str) and len(raw) <= _MAX_SYMBOL_LEN and raw in BATTLEROYALE_VALID:
            return raw
        return default
    else:  # stocks
        if not isinstance(raw, dict):
            return default
        action = raw.get("action")
        if action not in STOCKS_VALID:
            return default
        # Normalize to a fixed, bounded schema before the result crosses the
        # BotRunner→game-server boundary. Never forward the raw bot dict: a
        # bot can emit a huge symbol/quantity or nested objects at runtime
        # that would otherwise be pickled, serialized, and parsed every tick.
        normalized: dict = {"action": action}
        symbol = raw.get("symbol")
        if symbol is not None:
            if not isinstance(symbol, str) or len(symbol) > _MAX_SYMBOL_LEN:
                return default
            normalized["symbol"] = symbol
        quantity = raw.get("quantity")
        if quantity is not None:
            # bool is a subclass of int — reject it explicitly.
            if isinstance(quantity, bool) or not isinstance(quantity, int):
                return default
            if not (0 <= quantity <= _MAX_QUANTITY):
                return default
            normalized["quantity"] = quantity
        return normalized
