"""Cross-call isolation tests for the multiprocessing execution model.

The runner executes ONE fresh child process per /run call and tears it down after.
No state may leak from one call into the next — even when the same runner serves
different users' bots back-to-back. This invariant was previously only implicit in
"spawn a fresh process each time"; these tests lock it in so the forkserver switch
(BOT_MP_START_METHOD=forkserver) — and any future pooling — can't silently weaken it.

These must pass identically under both start methods (forkserver and spawn).
"""

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

BR_STATE = {"tick": 1, "my_bot": {"id": "b", "x": 5, "y": 5, "energy": 100}, "vision": []}


def _run(mode, code_hash, code, state, phase=None):
    return client.post("/run", json={
        "mode": mode, "bot_id": "b", "code_hash": code_hash,
        "code": code, "state": state, "phase": phase,
    }).json()


def test_module_monkeypatch_does_not_leak_across_calls():
    """A bot that monkeypatches an allowed stdlib module (math) must not affect the
    next call's view of that module. A reused/contaminated worker would leak it."""
    attacker = (
        "import math\n"
        "def action(state):\n"
        "    math.floor = lambda x: -99999\n"   # poison this child's math
        "    return 'STAY'\n"
    )
    victim = (
        "import math\n"
        "def action(state):\n"
        "    return 'MINE' if math.floor(3.9) == 3 else 'STAY'\n"
    )
    # Poison first, then a different bot checks math is clean.
    a = _run("battleroyale", "sha256:iso_attacker", attacker, BR_STATE)
    assert a["action"] == "STAY"
    v = _run("battleroyale", "sha256:iso_victim", victim, BR_STATE)
    assert v["action"] == "MINE"  # clean math.floor(3.9) == 3
    # And again, to be sure the poison never accumulates in a reused worker.
    v2 = _run("battleroyale", "sha256:iso_victim", victim, BR_STATE)
    assert v2["action"] == "MINE"


def test_global_mutation_does_not_leak_across_calls():
    """A bot that mutates a global it imported must not be observable next call."""
    writer = (
        "import math\n"
        "def action(state):\n"
        "    math._leaked = 'pwned'\n"           # stash a sentinel on a shared module
        "    return 'STAY'\n"
    )
    reader = (
        "import math\n"
        "def action(state):\n"
        # getattr/hasattr/dir are all forbidden; probe by direct access + try/except.
        "    try:\n"
        "        math._leaked\n"       # AttributeError if clean
        "        return 'STAY'\n"       # leaked!
        "    except AttributeError:\n"
        "        return 'MINE'\n"       # clean
    )
    assert _run("battleroyale", "sha256:iso_writer", writer, BR_STATE)["action"] == "STAY"
    assert _run("battleroyale", "sha256:iso_reader", reader, BR_STATE)["action"] == "MINE"


def test_one_bots_definitions_invisible_to_the_next():
    """A class/helper defined by one bot must not be reachable by the next bot's
    namespace (fresh exec namespace + fresh process)."""
    definer = (
        "class Sneaky:\n"
        "    secret = 42\n"
        "def action(state):\n"
        "    return 'STAY'\n"
    )
    probe = (
        "def action(state):\n"
        # NameError on Sneaky -> bot raises -> runner returns fallback STAY with ok False.
        "    return 'MINE' if Sneaky.secret == 42 else 'STAY'\n"
    )
    _run("battleroyale", "sha256:iso_definer", definer, BR_STATE)
    res = _run("battleroyale", "sha256:iso_probe", probe, BR_STATE)
    assert res["action"] == "STAY"  # Sneaky is undefined -> fallback
    assert res["ok"] is False


def test_forkserver_path_runs_all_modes():
    """Smoke: every mode/phase returns a valid result under the configured start
    method (guards the forkserver switch end-to-end, not just battleroyale)."""
    br = _run("battleroyale", "sha256:smoke_br",
              "def action(state): return 'MINE'", BR_STATE)
    assert br["ok"] is True and br["action"] == "MINE"

    st_state = {"tick": 1, "my_bot": {"id": "b", "cash": 1.0, "portfolio": {}}, "market": {"stocks": []}}
    st = _run("stocks", "sha256:smoke_st",
              "def action(state): return {'action': 'HOLD'}", st_state)
    assert st["ok"] is True and st["action"]["action"] == "HOLD"

    br2_code = (
        "class Bot(BattleRoyale2DBot):\n"
        "    def get_action(self, state):\n"
        "        return {'move_dir': [1.0, 0.0]}\n"
    )
    br2 = _run("battleroyale2", "sha256:smoke_br2", br2_code, {"hp": 100})
    assert br2["ok"] is True and br2["action"]["move_dir"] == [1.0, 0.0]

    spawn = _run("battleroyale2", "sha256:smoke_br2", br2_code,
                 {"map_size": [10, 10]}, phase="choose_spawn")
    assert spawn["ok"] is True
