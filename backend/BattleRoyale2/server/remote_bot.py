"""RemoteBattleRoyale2BotAdapter — Bot Runner HTTP API로 유저 BR2 봇을 실행하는 어댑터.

InProcessBot2(같은 프로세스 exec)의 격리 버전. 매 STATE마다 POST /run을 호출해
action dict를 받고, MATCH_INFO 시 phase="choose_spawn"으로 스폰 위치를 받는다.
Bot Runner가 timeout/에러/정책위반 시 _ZERO_ACTION(또는 None)을 폴백으로 반환한다.

봇 코드는 bot-runner 자식 프로세스(spawn + gVisor + rlimit + 필터드 builtins)에서만
실행되므로, 악성 코드가 game-server Pod의 DB/Firebase/GCS 자격에 접근할 수 없다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import urllib.request
from typing import Any

from BattleRoyale2.src.arena.bot_interface import BattleRoyale2DBot

logger = logging.getLogger(__name__)

_ZERO_ACTION = {
    "move_dir": [0.0, 0.0], "aim_dir": [1.0, 0.0],
    "attack": False, "guard": False, "dash": False,
    "pickup": False, "use_potion": False,
}


class RemoteBattleRoyale2BotAdapter(BattleRoyale2DBot):
    """Bot Runner(/run, mode=battleroyale2)를 호출해 BR2 봇을 격리 실행하는 어댑터."""

    def __init__(self, bot_id: str, code: str, runner_url: str, timeout: float = 0.5) -> None:
        self._bot_id = bot_id
        self._code = code
        self._code_hash = "sha256:" + hashlib.sha256(code.encode()).hexdigest()
        self._runner_url = runner_url.rstrip("/")
        self._timeout = timeout

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def _call(self, state: dict, phase: str | None = None) -> dict:
        payload = json.dumps({
            "mode": "battleroyale2",
            "bot_id": self._bot_id,
            "code_hash": self._code_hash,
            "code": self._code,
            "state": state,
            "phase": phase,
        }).encode()
        req = urllib.request.Request(
            f"{self._runner_url}/run",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read())

    def get_action(self, state: dict[str, Any]) -> dict[str, Any]:
        try:
            body = self._call(state)
            action = body.get("action")
            return action if isinstance(action, dict) else dict(_ZERO_ACTION)
        except Exception as e:  # noqa: BLE001
            logger.warning("[BR2] 봇 %s Bot Runner 호출 실패 → ZERO: %s", self._bot_id, e)
            return dict(_ZERO_ACTION)

    def choose_spawn(self, map_info: dict[str, Any]):
        try:
            body = self._call(map_info, phase="choose_spawn")
            pos = body.get("action")
            if isinstance(pos, (list, tuple)) and len(pos) == 2:
                return (float(pos[0]), float(pos[1]))
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning("[BR2] 봇 %s choose_spawn 호출 실패 → None: %s", self._bot_id, e)
            return None

    def on_episode_done(self, rank: int, n_bots: int, score: float) -> None:
        # 격리 실행은 상태를 영속할 수 없으므로(매 호출 새 프로세스 + RLIMIT_FSIZE=0) no-op.
        return None
