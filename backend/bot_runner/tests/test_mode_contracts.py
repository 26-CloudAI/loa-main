"""
Mode-specific action contract tests.
Verifies all 19 BattleRoyale actions and core MockStocks actions are accepted.
"""
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

BR_STATE = {
    "tick": 1, "my_bot": {"id": "b"}, "vision": [], "zone_boundary": 10, "leaderboard": []
}
ST_STATE = {
    "tick": 1,
    "my_bot": {"id": "b", "cash": 10000.0, "portfolio": {}, "total_value": 10000.0},
    "market": {"stocks": []},
    "leaderboard": [],
}

ALL_BR_ACTIONS = [
    "STAY",
    "MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT",
    "MOVE_UP_LEFT", "MOVE_UP_RIGHT", "MOVE_DOWN_LEFT", "MOVE_DOWN_RIGHT",
    "MINE",
    "ATTACK_UP", "ATTACK_DOWN", "ATTACK_LEFT", "ATTACK_RIGHT",
    "ATTACK_UP_LEFT", "ATTACK_UP_RIGHT", "ATTACK_DOWN_LEFT", "ATTACK_DOWN_RIGHT",
    "SHIELD",
]


@pytest.mark.parametrize("action", ALL_BR_ACTIONS)
def test_battleroyale_valid_action(action: str):
    resp = client.post("/run", json={
        "mode": "battleroyale",
        "bot_id": "b",
        "code_hash": f"sha256:br_{action}",
        "code": f"def action(state): return '{action}'",
        "state": BR_STATE,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["action"] == action


def test_battleroyale_default_is_stay():
    resp = client.post("/run", json={
        "mode": "battleroyale",
        "bot_id": "b",
        "code_hash": "sha256:br_default",
        "code": "def action(state): raise Exception('fail')",
        "state": BR_STATE,
    })
    assert resp.json()["action"] == "STAY"


def test_battleroyale_wrong_type_returns_stay():
    resp = client.post("/run", json={
        "mode": "battleroyale",
        "bot_id": "b",
        "code_hash": "sha256:br_wrong_type",
        "code": "def action(state): return 42",
        "state": BR_STATE,
    })
    assert resp.json()["action"] == "STAY"


def test_stocks_hold_action():
    resp = client.post("/run", json={
        "mode": "stocks",
        "bot_id": "b",
        "code_hash": "sha256:st_hold_c",
        "code": "def action(state): return {'action': 'HOLD'}",
        "state": ST_STATE,
    })
    assert resp.status_code == 200
    assert resp.json()["action"] == {"action": "HOLD"}


def test_stocks_buy_action():
    resp = client.post("/run", json={
        "mode": "stocks",
        "bot_id": "b",
        "code_hash": "sha256:st_buy_c",
        "code": "def action(state): return {'action': 'BUY', 'symbol': 'APEX', 'quantity': 5}",
        "state": ST_STATE,
    })
    data = resp.json()
    assert data["ok"] is True
    assert data["action"]["action"] == "BUY"


def test_stocks_sell_action():
    resp = client.post("/run", json={
        "mode": "stocks",
        "bot_id": "b",
        "code_hash": "sha256:st_sell_c",
        "code": "def action(state): return {'action': 'SELL', 'symbol': 'APEX', 'quantity': 3}",
        "state": ST_STATE,
    })
    assert resp.json()["action"]["action"] == "SELL"


def test_stocks_default_is_hold():
    resp = client.post("/run", json={
        "mode": "stocks",
        "bot_id": "b",
        "code_hash": "sha256:st_default",
        "code": "def action(state): raise Exception('fail')",
        "state": ST_STATE,
    })
    assert resp.json()["action"] == {"action": "HOLD"}


def test_stocks_wrong_type_returns_hold():
    resp = client.post("/run", json={
        "mode": "stocks",
        "bot_id": "b",
        "code_hash": "sha256:st_wrong_type",
        "code": "def action(state): return 'HOLD'",  # string, not dict
        "state": ST_STATE,
    })
    assert resp.json()["action"] == {"action": "HOLD"}


def test_stocks_invalid_action_key_returns_hold():
    resp = client.post("/run", json={
        "mode": "stocks",
        "bot_id": "b",
        "code_hash": "sha256:st_invalid_key",
        "code": "def action(state): return {'action': 'MOON'}",
        "state": ST_STATE,
    })
    assert resp.json()["action"] == {"action": "HOLD"}
