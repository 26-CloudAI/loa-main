"""AI Arena — 배틀로얄 도메인 패키지.

게임 엔진/타입은 backend/core/ 로 분리됨.
이 패키지에는 인증, DB, 랭킹, 샌드박스, 서버, GCS 등 도메인 로직만 포함.

하위 호환을 위해 core 모듈 일부를 재노출한다 (deprecated, 점진적 제거 권장).
"""

# core/는 battle_royale/ 의 형제 디렉토리(backend/core/)로 존재한다.
# 직접 실행/PYTHONPATH 누락 시에도 import 가능하도록 sys.path를 보정.
import sys as _sys
from pathlib import Path as _Path

_backend_dir = str(_Path(__file__).resolve().parents[3])
if _backend_dir not in _sys.path:
    _sys.path.insert(0, _backend_dir)

from core.bot_interface import BotInterface
from core.config import DEFAULT_CONFIG, GameConfig
from core.engine import GameEngine
from core.types import Action, Bot, GameResult, TickEvent

__all__ = [
    "BotInterface",
    "GameEngine",
    "GameConfig",
    "DEFAULT_CONFIG",
    "Action",
    "Bot",
    "GameResult",
    "TickEvent",
]
