"""유저 제출 Python 코드를 같은 프로세스에서 실행하는 BR2 봇 어댑터.

기존 battle_royale 의 InProcessBot 방식(제한 builtins + exec)을 BR2 에 맞춰 채용.
차이점:
- 유저는 `class Bot(BattleRoyale2DBot)` 를 정의 (get_action 은 dict 반환).
- import 는 화이트리스트(math/random/json 등)만 허용 — 기존은 import 전면 차단이지만
  BR2 봇 예시가 math/random 을 쓰므로 안전 모듈만 열어준다.
완전한 격리는 아니며(Docker/seccomp 가 진짜 방어선) 우발적 파일 IO·동적 import 차단 수준.
"""
from __future__ import annotations

import logging
from typing import Any

from BattleRoyale2.src.arena.bot_interface import BattleRoyale2DBot

logger = logging.getLogger(__name__)

# exec 시 제거할 builtins (파일 IO·동적 평가·대화형 차단)
_FORBIDDEN_BUILTINS = frozenset({
    "open", "exec", "eval", "compile",
    "input", "breakpoint", "memoryview", "globals", "vars",
})

# import 허용 모듈 화이트리스트
_ALLOWED_MODULES = frozenset({"math", "random", "json", "collections", "heapq", "itertools"})


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    root = name.split(".")[0]
    if root not in _ALLOWED_MODULES:
        raise ImportError("허용되지 않은 모듈 import: %s" % name)
    return __import__(name, globals, locals, fromlist, level)


def _restricted_builtins() -> dict:
    import builtins as _b
    safe = {}
    for n in dir(_b):
        if n.startswith("_"):
            continue
        if n in _FORBIDDEN_BUILTINS:
            continue
        safe[n] = getattr(_b, n)
    safe["__import__"] = _safe_import  # 화이트리스트 import 허용
    safe["__build_class__"] = _b.__build_class__  # class 정의에 필수 (dunder 라 위 루프서 제외됨)
    return safe


_RESTRICTED_BUILTINS = _restricted_builtins()

_ZERO_ACTION = {
    "move_dir": [0.0, 0.0], "aim_dir": [1.0, 0.0],
    "attack": False, "guard": False, "dash": False,
    "pickup": False, "use_potion": False,
}


class _UserBotBase:
    """유저 코드가 상속할 베이스 (exec 네임스페이스에 `BattleRoyale2DBot` 이름으로 주입).

    서버측 추상 인터페이스(BattleRoyale2DBot)와 달리 abstractmethod 가 없어
    인자 없이 인스턴스화 가능하고 get_action 만 override 하면 된다.
    bot_id 관리는 InProcessBot2 가 담당하므로 유저는 신경 쓸 필요 없음.
    """
    def choose_spawn(self, map_info):  # noqa: ARG002
        return None

    def get_action(self, state):  # noqa: ARG002
        return dict(_ZERO_ACTION)

    def on_episode_done(self, rank, n_bots, score):  # noqa: ARG002
        pass


class InProcessBot2(BattleRoyale2DBot):
    """유저 코드(`class Bot(BattleRoyale2DBot)`)를 인프로세스로 실행하는 어댑터."""

    def __init__(self, bot_id: str, code: str):
        self._bot_id = bot_id
        self._impl: BattleRoyale2DBot | None = None
        self._load_error: str | None = None
        try:
            ns: dict = {
                "__builtins__": _RESTRICTED_BUILTINS,
                "__name__": "user_bot_%s" % bot_id,
                "BattleRoyale2DBot": _UserBotBase,
            }
            exec(compile(code, "<user_bot:%s>" % bot_id, "exec"), ns)  # noqa: S102
            bot_cls = ns.get("Bot")
            if bot_cls is None or not isinstance(bot_cls, type) or not issubclass(bot_cls, _UserBotBase):
                raise ValueError("class Bot(BattleRoyale2DBot) 를 찾을 수 없습니다.")
            self._impl = bot_cls()
        except Exception as e:  # noqa: BLE001
            self._load_error = str(e)
            logger.warning("[BR2] 유저 봇 %s 로드 실패: %s", bot_id, e)

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict[str, Any]):
        if self._impl is None:
            return None
        try:
            return self._impl.choose_spawn(map_info)
        except Exception:  # noqa: BLE001
            logger.warning("[BR2] 봇 %s choose_spawn 오류", self._bot_id, exc_info=True)
            return None

    def get_action(self, state: dict[str, Any]) -> dict[str, Any]:
        if self._impl is None:
            return dict(_ZERO_ACTION)
        try:
            result = self._impl.get_action(state)
            return result if isinstance(result, dict) else dict(_ZERO_ACTION)
        except Exception:  # noqa: BLE001
            logger.warning("[BR2] 봇 %s get_action 오류 → STAY", self._bot_id, exc_info=True)
            return dict(_ZERO_ACTION)

    def on_episode_done(self, rank: int, n_bots: int, score: float) -> None:
        if self._impl is None:
            return
        try:
            self._impl.on_episode_done(rank, n_bots, score)
        except Exception:  # noqa: BLE001
            logger.warning("[BR2] 봇 %s on_episode_done 오류", self._bot_id, exc_info=True)
