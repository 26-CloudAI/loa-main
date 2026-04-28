"""
봇 인터페이스 추상 클래스.

유저가 제출하는 코드는 action(state) 함수 하나로 동작하며,
서버 내부에서는 InProcessBot이 이를 BotInterface로 감싼다.

state 구조:
  {
    "tick": int,
    "my_bot": {
        "id": str,
        "cash": float,
        "portfolio": {symbol: quantity},
        "total_value": float,
    },
    "market": {
        "stocks": [
            {
                "symbol": str,
                "price": float,
                "price_history": [float, ...],
                "change_pct": float,
            },
            ...
        ]
    },
    "leaderboard": [{"rank": int, "id": str, "total_value": float}, ...]
  }

반환값:
  {"action": "HOLD"}
  {"action": "BUY",  "symbol": "APEX", "quantity": 10}
  {"action": "SELL", "symbol": "APEX", "quantity": 5}
"""

from abc import ABC, abstractmethod


class BotInterface(ABC):
    def __init__(self, bot_id: str, **kwargs):
        self._bot_id = bot_id

    @property
    def bot_id(self) -> str:
        return self._bot_id

    @abstractmethod
    def get_action(self, state: dict) -> dict:
        ...
