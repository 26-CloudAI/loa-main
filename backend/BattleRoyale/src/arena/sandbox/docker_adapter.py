"""
AI Arena — Docker 봇 어댑터

BotInterface를 구현하여 엔진 코어와 Docker 컨테이너를 연결한다.
엔진 입장에서는 로컬 봇과 동일한 인터페이스로 호출.

통신 흐름:
  엔진 → DockerBotAdapter.get_action(state)
       → HTTP POST http://{container_ip}:8000/action
       → 컨테이너 내 wrapper → user_bot.action(state)
       → HTTP 응답 → DockerBotAdapter → 엔진
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Optional

from ..bot_interface import BotInterface
from .config import SandboxConfig

logger = logging.getLogger(__name__)


class DockerBotAdapter(BotInterface):
    """
    Docker 컨테이너 내 봇과 HTTP로 통신하는 어댑터.

    - get_action() 호출 시 컨테이너에 POST 요청
    - 타임아웃(100ms) 초과 시 "STAY" 반환
    - 어떤 오류가 발생해도 "STAY" 반환 (엔진 안정성 보장)
    """

    def __init__(
        self,
        bot_id: str,
        action_url: str,
        config: SandboxConfig,
    ):
        self._bot_id = bot_id
        self._action_url = action_url
        self._timeout = config.action_timeout_sec

        # 디버그용 통계
        self.total_calls: int = 0
        self.timeout_count: int = 0
        self.error_count: int = 0

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def get_action(self, state: dict) -> str:
        """
        컨테이너에 state를 전송하고 action을 수신한다.

        타임아웃, 네트워크 오류, JSON 파싱 실패, 유효하지 않은 액션 등
        모든 예외 상황에서 "STAY"를 반환한다.
        """
        self.total_calls += 1

        try:
            payload = json.dumps(state).encode("utf-8")

            req = urllib.request.Request(
                self._action_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
                data = json.loads(raw)
                action = data.get("action", "STAY")

                if data.get("error"):
                    logger.debug(
                        "Bot %s 컨테이너 경고: %s",
                        self._bot_id, data["error"],
                    )

                return action

        except (TimeoutError, OSError) as e:
            # socket.timeout (Python 3.3+에서 TimeoutError의 alias)
            # 읽기 타임아웃 시 urlopen이 직접 발생시킴
            if _is_timeout_error(e):
                self.timeout_count += 1
                logger.debug("Bot %s 타임아웃 (%s초)", self._bot_id, self._timeout)
            else:
                self.error_count += 1
                logger.debug(
                    "Bot %s 네트워크 오류: %s", self._bot_id, e, exc_info=True,
                )
            return "STAY"

        except urllib.error.URLError as e:
            # 연결 실패, DNS 오류 등
            if _is_timeout_error(e):
                self.timeout_count += 1
                logger.debug("Bot %s 타임아웃 (%s초)", self._bot_id, self._timeout)
            else:
                self.error_count += 1
                logger.debug(
                    "Bot %s 네트워크 오류: %s", self._bot_id, e, exc_info=True,
                )
            return "STAY"

        except Exception as e:
            self.error_count += 1
            logger.debug(
                "Bot %s 예상치 못한 오류: %s", self._bot_id, e, exc_info=True,
            )
            return "STAY"

    def get_stats(self) -> dict:
        """디버그/모니터링용 통계."""
        return {
            "bot_id": self._bot_id,
            "total_calls": self.total_calls,
            "timeout_count": self.timeout_count,
            "error_count": self.error_count,
            "success_rate": (
                (self.total_calls - self.timeout_count - self.error_count)
                / max(self.total_calls, 1)
            ),
        }


def _is_timeout_error(error: Exception) -> bool:
    """주어진 예외가 타임아웃에 의한 것인지 판별."""
    import socket

    # 직접적인 타임아웃 예외
    if isinstance(error, (socket.timeout, TimeoutError)):
        return True

    # URLError가 감싼 타임아웃
    reason = getattr(error, "reason", None)
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return True
    if isinstance(reason, OSError) and "timed out" in str(reason).lower():
        return True

    # 문자열 포함 판별 (fallback)
    return "timed out" in str(error).lower()
