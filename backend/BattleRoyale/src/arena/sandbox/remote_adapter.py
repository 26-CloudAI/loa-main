"""
RemoteBattleRoyaleBotAdapter — Bot Runner HTTP API를 통해 유저 봇을 실행하는 어댑터.

매 tick마다 POST /run을 호출해 action을 받는다.
Bot Runner가 timeout/에러 시 STAY를 fallback으로 반환한다.
"""

from __future__ import annotations

import hashlib
import logging
import urllib.error
import urllib.request
import json

from ..bot_interface import BotInterface

logger = logging.getLogger(__name__)

_FALLBACK = "STAY"


class RemoteBattleRoyaleBotAdapter(BotInterface):
    """Bot Runner HTTP API를 호출해 action을 받는 어댑터."""

    def __init__(
        self,
        bot_id: str,
        code: str,
        runner_url: str,
        timeout: float = 0.5,
    ) -> None:
        self._bot_id = bot_id
        self._code = code
        self._code_hash = "sha256:" + hashlib.sha256(code.encode()).hexdigest()
        self._runner_url = runner_url.rstrip("/")
        self._timeout = timeout

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def get_action(self, state: dict) -> str:
        payload = json.dumps({
            "mode": "battleroyale",
            "bot_id": self._bot_id,
            "code_hash": self._code_hash,
            "code": self._code,
            "state": state,
        }).encode()

        try:
            req = urllib.request.Request(
                f"{self._runner_url}/run",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = json.loads(resp.read())

            action = body.get("action", _FALLBACK)
            if not isinstance(action, str):
                return _FALLBACK
            return action

        except Exception as e:
            logger.warning("봇 %s Bot Runner 호출 실패, STAY 처리: %s", self._bot_id, e)
            return _FALLBACK
