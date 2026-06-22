"""bot-runner battleroyale2 모드 테스트.

BR2 봇은 `class Bot(BattleRoyale2DBot)` + get_action()->dict / choose_spawn().
액션은 bounded 스키마로 정규화, 위험 코드는 policy/격리로 차단, 실패 시 ZERO 액션 폴백.
"""
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

BR2_STATE = {"self": {"pos": [0, 0], "hp": 100}, "vision": {}, "zone": {}}

ZERO = {
    "move_dir": [0.0, 0.0], "aim_dir": [1.0, 0.0],
    "attack": False, "guard": False, "dash": False,
    "pickup": False, "use_potion": False,
}


def _run(code, code_hash, state=None, phase=None):
    payload = {
        "mode": "battleroyale2", "bot_id": "b", "code_hash": code_hash,
        "code": code, "state": state if state is not None else BR2_STATE,
    }
    if phase is not None:
        payload["phase"] = phase
    return client.post("/run", json=payload)


def test_br2_valid_action_normalized():
    code = (
        "class Bot(BattleRoyale2DBot):\n"
        "    def get_action(self, state):\n"
        "        return {'move_dir': [0.5, 0.5], 'attack': True}\n"
    )
    data = _run(code, "sha256:br2_valid").json()
    assert data["ok"] is True
    a = data["action"]
    assert a["move_dir"] == [0.5, 0.5]
    assert a["attack"] is True
    assert a["aim_dir"] == [1.0, 0.0]   # 기본값 채움
    assert a["guard"] is False


def test_br2_no_bot_class_defaults_zero():
    data = _run("x = 1", "sha256:br2_nobot").json()
    assert data["ok"] is False
    assert data["action"] == ZERO


def test_br2_exception_defaults_zero():
    code = (
        "class Bot(BattleRoyale2DBot):\n"
        "    def get_action(self, state):\n"
        "        raise ValueError('boom')\n"
    )
    data = _run(code, "sha256:br2_exc").json()
    assert data["ok"] is False
    assert data["action"] == ZERO


def test_br2_non_dict_action_coerced_zero():
    code = (
        "class Bot(BattleRoyale2DBot):\n"
        "    def get_action(self, state):\n"
        "        return 'not a dict'\n"
    )
    data = _run(code, "sha256:br2_str").json()
    assert data["ok"] is True
    assert data["action"] == ZERO


def test_br2_non_finite_vector_defaults():
    code = (
        "class Bot(BattleRoyale2DBot):\n"
        "    def get_action(self, state):\n"
        "        return {'move_dir': [1e309, 0.0]}\n"   # 1e309 == inf
    )
    data = _run(code, "sha256:br2_inf").json()
    assert data["ok"] is True
    assert data["action"]["move_dir"] == [0.0, 0.0]


def test_br2_import_math_allowed():
    code = (
        "import math\n"
        "class Bot(BattleRoyale2DBot):\n"
        "    def get_action(self, state):\n"
        "        return {'move_dir': [math.cos(0.0), 0.0]}\n"
    )
    data = _run(code, "sha256:br2_math").json()
    assert data["ok"] is True
    assert data["action"]["move_dir"] == [1.0, 0.0]


def test_br2_import_os_blocked():
    code = (
        "import os\n"
        "class Bot(BattleRoyale2DBot):\n"
        "    def get_action(self, state):\n"
        "        return {}\n"
    )
    data = _run(code, "sha256:br2_os").json()
    assert data["ok"] is False
    assert "forbidden import" in (data["error"] or "")


def test_br2_open_blocked():
    code = (
        "class Bot(BattleRoyale2DBot):\n"
        "    def get_action(self, state):\n"
        "        return open('/etc/passwd').read()\n"
    )
    data = _run(code, "sha256:br2_open").json()
    assert data["ok"] is False


def test_br2_choose_spawn_returns_position():
    code = (
        "class Bot(BattleRoyale2DBot):\n"
        "    def choose_spawn(self, map_info):\n"
        "        return (10.0, 20.0)\n"
        "    def get_action(self, state):\n"
        "        return {}\n"
    )
    data = _run(code, "sha256:br2_spawn", state={"map_size": [100, 100]}, phase="choose_spawn").json()
    assert data["ok"] is True
    assert data["action"] == [10.0, 20.0]


def test_br2_choose_spawn_default_none():
    code = (
        "class Bot(BattleRoyale2DBot):\n"
        "    def get_action(self, state):\n"
        "        return {}\n"
    )
    data = _run(code, "sha256:br2_spawn_none", state={}, phase="choose_spawn").json()
    assert data["ok"] is True
    assert data["action"] is None


def test_br2_infinite_loop_returns_zero():
    code = (
        "class Bot(BattleRoyale2DBot):\n"
        "    def get_action(self, state):\n"
        "        while True:\n"
        "            pass\n"
    )
    data = _run(code, "sha256:br2_loop").json()
    assert data["ok"] is False
    assert data["action"] == ZERO
