"""Regression tests for the Codex adversarial-review hardening (2026-05-26).

Covers three findings:
  1. stocks output is normalized to a bounded schema before crossing the
     BotRunner -> game-server boundary (oversized-output DoS).
  2. SAFE_BUILTINS is an allowlist: site-injected helper objects
     (license/help/credits/copyright) and capability builtins are gone.
  3. legitimate bots (class defs, try/except, common builtins) still work.
"""

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

BR_STATE = {"tick": 1, "my_bot": {"id": "b", "x": 5, "y": 5, "energy": 100}, "vision": []}
ST_STATE = {"tick": 1, "my_bot": {"id": "b", "cash": 10000.0, "portfolio": {}}, "market": {"stocks": []}}


def _run(mode, code_hash, code, state):
    return client.post("/run", json={
        "mode": mode, "bot_id": "b", "code_hash": code_hash, "code": code, "state": state,
    }).json()


# --- Finding 2: stocks output normalization -------------------------------

def test_stocks_oversized_symbol_returns_hold():
    code = "def action(state): return {'action': 'BUY', 'symbol': 'A' * 100000, 'quantity': 1}"
    data = _run("stocks", "sha256:dos_sym", code, ST_STATE)
    assert data["action"] == {"action": "HOLD"}


def test_stocks_huge_quantity_returns_hold():
    code = "def action(state): return {'action': 'BUY', 'symbol': 'APEX', 'quantity': 10**18}"
    data = _run("stocks", "sha256:dos_qty", code, ST_STATE)
    assert data["action"] == {"action": "HOLD"}


def test_stocks_nested_quantity_returns_hold():
    code = "def action(state): return {'action': 'SELL', 'symbol': 'APEX', 'quantity': [1, 2, 3]}"
    data = _run("stocks", "sha256:dos_nested", code, ST_STATE)
    assert data["action"] == {"action": "HOLD"}


def test_stocks_bool_quantity_returns_hold():
    # bool is an int subclass; must be rejected, not coerced.
    code = "def action(state): return {'action': 'BUY', 'symbol': 'APEX', 'quantity': True}"
    data = _run("stocks", "sha256:dos_bool", code, ST_STATE)
    assert data["action"] == {"action": "HOLD"}


def test_stocks_extra_keys_are_stripped():
    code = ("def action(state): return {'action': 'BUY', 'symbol': 'APEX', "
            "'quantity': 5, 'evil': 'x' * 100000, 'nested': {'a': [1, 2]}}")
    data = _run("stocks", "sha256:dos_extra", code, ST_STATE)
    assert data["ok"] is True
    assert data["action"] == {"action": "BUY", "symbol": "APEX", "quantity": 5}


def test_stocks_valid_full_action_passes():
    code = "def action(state): return {'action': 'BUY', 'symbol': 'APEX', 'quantity': 10}"
    data = _run("stocks", "sha256:dos_ok", code, ST_STATE)
    assert data["ok"] is True
    assert data["action"] == {"action": "BUY", "symbol": "APEX", "quantity": 10}


# --- Finding 3: SAFE_BUILTINS allowlist -----------------------------------

def test_site_helper_license_not_accessible():
    # str(license) on the site helper reads license._Printer__filenames files.
    code = "def action(state): return str(license)"
    data = _run("battleroyale", "sha256:esc_license", code, BR_STATE)
    assert data["ok"] is False
    assert data["action"] == "STAY"


def test_site_helpers_and_caps_blocked():
    for name in ("help", "credits", "copyright", "exit", "quit", "open", "eval", "exec", "getattr"):
        code = f"def action(state): return {name}"
        data = _run("battleroyale", f"sha256:esc_{name}", code, BR_STATE)
        assert data["ok"] is False, f"{name} should be unavailable"
        assert data["action"] == "STAY"


# --- Finding 3 regression: legitimate bots still run ----------------------

def test_class_defining_bot_still_works():
    code = (
        "class Helper:\n"
        "    def pick(self):\n"
        "        return 'MOVE_UP'\n"
        "def action(state):\n"
        "    return Helper().pick()\n"
    )
    data = _run("battleroyale", "sha256:cls_bot", code, BR_STATE)
    assert data["ok"] is True
    assert data["action"] == "MOVE_UP"


def test_super_and_inheritance_still_works():
    code = (
        "class Base:\n"
        "    def act(self):\n"
        "        return 'SHIELD'\n"
        "class Bot(Base):\n"
        "    def go(self):\n"
        "        return super().act()\n"
        "def action(state):\n"
        "    return Bot().go()\n"
    )
    data = _run("battleroyale", "sha256:super_bot", code, BR_STATE)
    assert data["ok"] is True
    assert data["action"] == "SHIELD"


def test_try_except_and_common_builtins_still_work():
    code = (
        "def action(state):\n"
        "    try:\n"
        "        vals = [3, 1, 2]\n"
        "        n = max(vals) - min(vals) + len(vals) + abs(-1)\n"
        "        _ = sorted(vals)\n"
        "        if n > 100:\n"
        "            raise ValueError('x')\n"
        "        return 'MINE'\n"
        "    except ValueError:\n"
        "        return 'STAY'\n"
    )
    data = _run("battleroyale", "sha256:builtins_bot", code, BR_STATE)
    assert data["ok"] is True
    assert data["action"] == "MINE"


# --- classic-mode imports: templates start with `import random`/`import math` -

def test_battleroyale_import_random_works():
    code = (
        "import random\n"
        "def action(state):\n"
        "    random.seed(0)\n"
        "    return 'MINE'\n"
    )
    data = _run("battleroyale", "sha256:imp_random", code, BR_STATE)
    assert data["ok"] is True
    assert data["action"] == "MINE"


def test_stocks_import_math_works():
    code = (
        "import math\n"
        "def action(state):\n"
        "    return {'action': 'BUY', 'symbol': 'APEX', 'quantity': int(math.floor(5.9))}\n"
    )
    data = _run("stocks", "sha256:imp_math", code, ST_STATE)
    assert data["ok"] is True
    assert data["action"] == {"action": "BUY", "symbol": "APEX", "quantity": 5}


def test_battleroyale_forbidden_import_blocked():
    code = "import os\ndef action(state): return 'STAY'\n"
    data = _run("battleroyale", "sha256:imp_os", code, BR_STATE)
    assert data["ok"] is False


def test_battleroyale_non_allowlisted_import_blocked():
    # base64 is not in policy's forbidden list, so it passes the AST check —
    # the runtime _safe_import allowlist is what blocks it.
    code = "import base64\ndef action(state): return 'STAY'\n"
    data = _run("battleroyale", "sha256:imp_b64", code, BR_STATE)
    assert data["ok"] is False
    assert data["action"] == "STAY"
