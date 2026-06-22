"""
Isolated bot execution via multiprocessing.

Security layers applied in each child process:
  1. os.environ.clear()   — remove all inherited secrets
  2. resource limits      — CPU time, address space, file size, process count
  3. signal.SIGALRM       — hard timeout inside the child
  4. filtered __builtins__ — dangerous built-ins removed from exec namespace
  5. gVisor (at Pod level) — syscall filtering (outside this file)

Isolation model: ONE fresh child process per request, torn down after the call —
no state ever crosses calls. The multiprocessing start method only changes *how*
that fresh child is created, not the per-call isolation:

  * forkserver (default): a clean, single-threaded server process imports this
    module once (preload) and fork()s a fresh child per request. Under gVisor this
    is ~5x cheaper than spawn (no interpreter restart, no module re-import) while
    keeping identical isolation — the forkserver never runs bot code so it can't be
    contaminated, and each forked child still serves exactly one call then exits.
  * spawn (fallback): re-execs a fresh Python interpreter per request. Correct but
    slow under gVisor (~120ms+ of CPU per call), which throttles BR2's lock-step
    real-time loop. Used automatically if forkserver is unavailable.

Controlled by BOT_MP_START_METHOD (default "forkserver").
"""

from __future__ import annotations

import builtins as _builtins_module
import logging
import math
import multiprocessing
import os
import resource
import signal
from typing import Any, Tuple

logger = logging.getLogger(__name__)

# Start method: forkserver by default (fast under gVisor, same per-call isolation),
# spawn as automatic fallback. See module docstring.
_START_METHOD = os.environ.get("BOT_MP_START_METHOD", "forkserver").strip().lower()


def _make_context():
    """Build the multiprocessing context. forkserver preloads this module in a clean
    server process so forked children skip interpreter restart + re-import. Falls back
    to spawn if forkserver can't be initialised (e.g. unsupported platform)."""
    if _START_METHOD == "forkserver":
        try:
            ctx = multiprocessing.get_context("forkserver")
            try:
                # Preload so the forkserver (and thus every forked child) already has
                # this module — best-effort; children import it lazily if preload fails.
                ctx.set_forkserver_preload(["executor"])
            except Exception:  # noqa: BLE001
                logger.warning("forkserver preload failed; children import lazily", exc_info=True)
            return ctx
        except Exception:  # noqa: BLE001
            logger.warning("forkserver unavailable; falling back to spawn", exc_info=True)
    return multiprocessing.get_context("spawn")


# One fresh child process per call; only the *creation* mechanism changes.
_mp_ctx = _make_context()

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


# Modules user bot code may import. All pure-computation stdlib (no file/
# network/process I/O). Classic battleroyale/stocks templates and BR2 bots
# alike start with `import random`/`import math`. policy.check() blocks
# dangerous modules (os/sys/...) at the AST layer before exec; this allowlist
# is the matching runtime gate, and the only modules __import__ will load.
_ALLOWED_MODULES = frozenset({"math", "random", "json", "collections", "heapq", "itertools"})


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    root = name.split(".")[0]
    if root not in _ALLOWED_MODULES:
        raise ImportError("import not allowed: %s" % name)
    return __import__(name, globals, locals, fromlist, level)


def _build_safe_builtins() -> dict:
    src = vars(_builtins_module)
    safe = {name: src[name] for name in _ALLOWED_BUILTINS if name in src}
    # Exception classes are harmless and required for try/except in bot code.
    for name, val in src.items():
        if isinstance(val, type) and issubclass(val, BaseException):
            safe[name] = val
    # Whitelisted __import__ so `import math`/`import random` statements resolve.
    # Direct __import__("os") calls are still rejected by policy.check() as a
    # forbidden call, and _safe_import bounds loads to _ALLOWED_MODULES.
    safe["__import__"] = _safe_import
    return safe


# Computed once at import; child re-imports this module under spawn and recomputes.
SAFE_BUILTINS: dict = _build_safe_builtins()


# ── battleroyale2 (BR2) mode ────────────────────────────────────────────────
# BR2 bots are `class Bot(BattleRoyale2DBot)` with get_action()/choose_spawn(),
# returning a continuous-vector action dict — unlike the classic battleroyale
# (string) / stocks (dict) contracts. They share SAFE_BUILTINS (incl. the
# whitelisted __import__); only the injected base class differs.
BR2_ZERO_ACTION = {
    "move_dir": [0.0, 0.0], "aim_dir": [1.0, 0.0],
    "attack": False, "guard": False, "dash": False,
    "pickup": False, "use_potion": False,
}


class _BR2BotBase:
    """Injected as `BattleRoyale2DBot` into the bot namespace. Non-abstract so
    user code can subclass and override only get_action()."""

    def choose_spawn(self, map_info):  # noqa: ARG002
        return None

    def get_action(self, state):  # noqa: ARG002
        return dict(BR2_ZERO_ACTION)

    def on_episode_done(self, rank, n_bots, score):  # noqa: ARG002
        pass


def _default_for(mode: str) -> Any:
    if mode == "battleroyale":
        return "STAY"
    if mode == "battleroyale2":
        return dict(BR2_ZERO_ACTION)
    return {"action": "HOLD"}

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
    phase: str | None = None,
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
        if mode == "battleroyale2":
            # BR2: user defines `class Bot(BattleRoyale2DBot)`. Instantiate per
            # call (stateless across ticks — the runner spawns a fresh process
            # every request), then dispatch get_action / choose_spawn by phase.
            ns = {"__builtins__": SAFE_BUILTINS, "__name__": "__bot__",
                  "BattleRoyale2DBot": _BR2BotBase}
            exec(compiled, ns)  # noqa: S102
            bot_cls = ns.get("Bot")
            if not (isinstance(bot_cls, type) and issubclass(bot_cls, _BR2BotBase)):
                result_queue.put(("error", "no class Bot(BattleRoyale2DBot) defined"))
                return
            bot = bot_cls()
            if phase == "choose_spawn":
                result_queue.put(("ok", _validate_spawn(bot.choose_spawn(state))))
            else:
                result_queue.put(("ok", _validate_br2_action(bot.get_action(state))))
            return

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
        result_queue.put(("ok", _validate(result, mode, _default_for(mode))))
    except Exception as exc:
        result_queue.put(("error", str(exc)))


def run(
    source_code: str,
    state: dict,
    mode: str,
    action_timeout_sec: float,
    phase: str | None = None,
) -> Tuple[bool, Any, str]:
    """
    Spawn a child process, run user bot code, and return (ok, action, error).
    Always returns a valid fallback action on failure — never raises.

    Parent join timeout = action_timeout_sec + _PROCESS_GRACE_SEC (spawn/import
    overhead). Kept tight so an abandoned request frees its worker quickly
    rather than lingering for seconds after the game server's HTTP call timed out.
    """
    default: Any = _default_for(mode)
    process_timeout = action_timeout_sec + _PROCESS_GRACE_SEC

    q: multiprocessing.SimpleQueue = _mp_ctx.SimpleQueue()
    proc = _mp_ctx.Process(
        target=_child_entry,
        args=(source_code, state, q, action_timeout_sec, mode, phase),
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


def warmup() -> None:
    """Start the multiprocessing machinery (forkserver server process / spawn
    bootstrap) ahead of the first real request, so the first game tick doesn't pay
    cold-start. Runs one throwaway execution. Safe to call repeatedly; never raises.

    Must be called at runtime (e.g. FastAPI startup), NOT at import time — the
    forkserver preloads this module, and an import-time start would recurse.
    """
    try:
        run("def action(state):\n    return 'STAY'\n", {}, "battleroyale", 0.1, None)
    except Exception:  # noqa: BLE001
        logger.warning("bot-runner warmup failed (non-fatal)", exc_info=True)


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


def _br2_vec(value: Any, default: list) -> list:
    """Normalize a 2D vector to [float, float]; reject malformed/non-finite."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return list(default)
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return list(default)
    if not (math.isfinite(x) and math.isfinite(y)):
        return list(default)
    return [x, y]


def _validate_br2_action(raw: Any) -> dict:
    """Coerce a BR2 bot action to the fixed, bounded schema before it crosses
    the BotRunner→game-server boundary (mirrors ws_server._validate_action)."""
    if not isinstance(raw, dict):
        raw = {}
    return {
        "move_dir": _br2_vec(raw.get("move_dir"), [0.0, 0.0]),
        "aim_dir": _br2_vec(raw.get("aim_dir"), [1.0, 0.0]),
        "attack": bool(raw.get("attack", False)),
        "guard": bool(raw.get("guard", False)),
        "dash": bool(raw.get("dash", False)),
        "pickup": bool(raw.get("pickup", False)),
        "use_potion": bool(raw.get("use_potion", False)),
    }


def _validate_spawn(raw: Any):
    """choose_spawn → [x, y] finite floats, or None (engine picks randomly)."""
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return None
    try:
        x, y = float(raw[0]), float(raw[1])
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return [x, y]
