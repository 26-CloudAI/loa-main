import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

BR_STATE = {
    "tick": 1,
    "my_bot": {"id": "bot1", "x": 5, "y": 5, "energy": 100, "score": 0.0},
    "vision": [],
    "zone_boundary": 10,
    "leaderboard": [],
}

ST_STATE = {
    "tick": 1,
    "my_bot": {"id": "bot1", "cash": 10000.0, "portfolio": {}, "total_value": 10000.0},
    "market": {"stocks": [{"symbol": "APEX", "price": 100.0, "price_history": [100.0], "change_pct": 0.0}]},
    "leaderboard": [],
}


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_battleroyale_stay():
    resp = client.post("/run", json={
        "mode": "battleroyale",
        "bot_id": "bot1",
        "code_hash": "sha256:br_stay",
        "code": "def action(state): return 'STAY'",
        "state": BR_STATE,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["action"] == "STAY"


def test_battleroyale_move_up():
    resp = client.post("/run", json={
        "mode": "battleroyale",
        "bot_id": "bot1",
        "code_hash": "sha256:br_move_up",
        "code": "def action(state): return 'MOVE_UP'",
        "state": BR_STATE,
    })
    assert resp.status_code == 200
    assert resp.json()["action"] == "MOVE_UP"


def test_stocks_hold():
    resp = client.post("/run", json={
        "mode": "stocks",
        "bot_id": "bot1",
        "code_hash": "sha256:st_hold",
        "code": "def action(state): return {'action': 'HOLD'}",
        "state": ST_STATE,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["action"] == {"action": "HOLD"}


def test_stocks_buy():
    resp = client.post("/run", json={
        "mode": "stocks",
        "bot_id": "bot1",
        "code_hash": "sha256:st_buy",
        "code": "def action(state): return {'action': 'BUY', 'symbol': 'APEX', 'quantity': 10}",
        "state": ST_STATE,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["action"]["action"] == "BUY"
    assert data["action"]["symbol"] == "APEX"


def test_syntax_error_returns_fallback():
    resp = client.post("/run", json={
        "mode": "battleroyale",
        "bot_id": "bot1",
        "code_hash": "sha256:syntax_err",
        "code": "def action(state):\n  return 'STAY'\n invalid",
        "state": BR_STATE,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["action"] == "STAY"
    assert data["error"] is not None


def test_no_action_function_returns_fallback():
    resp = client.post("/run", json={
        "mode": "battleroyale",
        "bot_id": "bot1",
        "code_hash": "sha256:no_fn",
        "code": "x = 42",
        "state": BR_STATE,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["action"] == "STAY"


def test_invalid_battleroyale_action_returns_stay():
    resp = client.post("/run", json={
        "mode": "battleroyale",
        "bot_id": "bot1",
        "code_hash": "sha256:invalid_action",
        "code": "def action(state): return 'JUMP'",
        "state": BR_STATE,
    })
    assert resp.status_code == 200
    assert resp.json()["action"] == "STAY"


def test_invalid_stocks_action_returns_hold():
    resp = client.post("/run", json={
        "mode": "stocks",
        "bot_id": "bot1",
        "code_hash": "sha256:invalid_st",
        "code": "def action(state): return {'action': 'YOLO'}",
        "state": ST_STATE,
    })
    assert resp.status_code == 200
    assert resp.json()["action"] == {"action": "HOLD"}


def test_runtime_exception_returns_fallback():
    resp = client.post("/run", json={
        "mode": "battleroyale",
        "bot_id": "bot1",
        "code_hash": "sha256:runtime_exc",
        "code": "def action(state): raise ValueError('boom')",
        "state": BR_STATE,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["action"] == "STAY"


def test_forbidden_import_returns_fallback():
    resp = client.post("/run", json={
        "mode": "battleroyale",
        "bot_id": "bot1",
        "code_hash": "sha256:bad_import",
        "code": "import os\ndef action(state): return 'STAY'",
        "state": BR_STATE,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["action"] == "STAY"
    assert "forbidden" in data["error"]


def test_cache_hit_no_code_needed():
    # First request: populate cache
    resp1 = client.post("/run", json={
        "mode": "battleroyale",
        "bot_id": "bot1",
        "code_hash": "sha256:cache_test",
        "code": "def action(state): return 'SHIELD'",
        "state": BR_STATE,
    })
    assert resp1.json()["action"] == "SHIELD"

    # Second request: cache hit, no code provided
    resp2 = client.post("/run", json={
        "mode": "battleroyale",
        "bot_id": "bot1",
        "code_hash": "sha256:cache_test",
        "state": BR_STATE,
    })
    assert resp2.status_code == 200
    assert resp2.json()["action"] == "SHIELD"


def test_cache_miss_without_code_returns_error():
    resp = client.post("/run", json={
        "mode": "battleroyale",
        "bot_id": "bot1",
        "code_hash": "sha256:never_cached_xyz",
        "state": BR_STATE,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["action"] == "STAY"
    assert "cache miss" in data["error"]


def test_stocks_runtime_exception_returns_hold():
    resp = client.post("/run", json={
        "mode": "stocks",
        "bot_id": "bot1",
        "code_hash": "sha256:st_exc",
        "code": "def action(state): raise RuntimeError('oops')",
        "state": ST_STATE,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["action"] == {"action": "HOLD"}
