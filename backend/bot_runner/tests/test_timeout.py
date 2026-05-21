"""
Timeout tests spawn real child processes and may take several seconds.
BOT_ACTION_TIMEOUT_SEC is set low but signal.alarm uses integer seconds (min 1s).
"""
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

BR_STATE = {
    "tick": 1, "my_bot": {"id": "b"}, "vision": [], "zone_boundary": 10, "leaderboard": []
}


def test_infinite_loop_returns_stay(tmp_path):
    """Bot with infinite loop must timeout and return STAY fallback."""
    resp = client.post(
        "/run",
        json={
            "mode": "battleroyale",
            "bot_id": "bot1",
            "code_hash": "sha256:infinite_loop",
            "code": "def action(state):\n    while True: pass",
            "state": BR_STATE,
        },
        timeout=15,  # test-level timeout; process timeout is action_timeout + 5s
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["action"] == "STAY"
    assert data["error"] is not None


def test_cpu_hog_returns_stay():
    """Bot that burns CPU must be killed by resource limit or timeout."""
    resp = client.post(
        "/run",
        json={
            "mode": "battleroyale",
            "bot_id": "bot1",
            "code_hash": "sha256:cpu_hog",
            "code": "def action(state):\n    x = 0\n    while True: x += 1",
            "state": BR_STATE,
        },
        timeout=15,
    )
    assert resp.status_code == 200
    assert resp.json()["action"] == "STAY"
