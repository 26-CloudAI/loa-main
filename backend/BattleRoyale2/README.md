# BattleRoyale2 — 연속 2D 배틀로얄 백엔드

[loa-battleroyale-game](https://github.com/26-CloudAI/loa-battleroyale-game) (Godot 3.6 클라이언트) 와 WebSocket 으로 연결되어 봇 의사결정을 담당한다.

기존 `BattleRoyale` 패키지(그리드 + 11개 action) 와 별개 시스템이며, 클라이언트의 [PROTOCOL.md](https://github.com/26-CloudAI/loa-battleroyale-game/blob/main/PROTOCOL.md) / [GAME_RULES.md](https://github.com/26-CloudAI/loa-battleroyale-game/blob/main/GAME_RULES.md) 에 명시된 연속 2D 좌표·행동 스키마를 따른다.

## 구조

```
BattleRoyale2/
├── README.md                       # 본 문서
├── run_server.py                   # WS 서버 엔트리포인트
├── src/arena/
│   └── bot_interface.py            # BattleRoyale2DBot 추상 클래스
├── bots/
│   ├── __init__.py
│   ├── herbivore.py                # HerbivoreBot — 코인 채집 + 적 회피 + 자기장 사전 회피
│   ├── mad_dog.py                  # MadDogBot — 사거리 안 적 무조건 공격, 멀면 추격(dash)
│   └── camper.py                   # CamperBot — 초반 클러스터 회피 파밍, 중후반(t>=80s) 또는 스펙 충족 시 교전
└── server/
    └── ws_server.py                # FastAPI WebSocket 엔드포인트
```

## 실행

```bash
# 사전 조건: fastapi uvicorn 설치
pip install "fastapi>=0.104" "uvicorn[standard]>=0.24"

# 서버 기동 (기본 ws://127.0.0.1:8765)
cd loa-backend/backend
python -m BattleRoyale2.run_server --port 8765
```

Godot 클라이언트는 `ws://127.0.0.1:8765/battleroyale/match/<match_id>` 로 접속한다.

## 봇 작성

`BattleRoyale2DBot` 를 상속해 `get_action(state)` 를 구현. 예시:

```python
from BattleRoyale2.src.arena.bot_interface import BattleRoyale2DBot

class MyBot(BattleRoyale2DBot):
    def __init__(self, bot_id: str):
        self._bot_id = bot_id

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def get_action(self, state):
        return {
            "move_dir": [1.0, 0.0],
            "aim_dir": [1.0, 0.0],
            "attack": False,
            "guard": False,
            "dash": False,
            "pickup": False,
            "use_potion": False,
        }
```

`state` / `action` 스키마는 `bot_interface.py` 의 docstring 또는 클라이언트 측 GAME_RULES.md §9 참조.

## 프로토콜 (요약)

| 방향 | 메시지 | 시점 |
|---|---|---|
| C→S | HELLO | 연결 직후 1회 |
| S→C | MATCH_CONFIG | HELLO 수신 직후 자동 |
| S→C | MATCH_START | MATCH_CONFIG 직후 |
| C→S | MATCH_INFO | (선택) 매치 정보 보내고 SPAWN_CHOICES 받기 |
| S→C | SPAWN_CHOICES | 봇별 choose_spawn() 결과 |
| C→S | STATE (매 100ms) | 봇 시점별 vision 묶음 |
| S→C | ACTIONS (응답) | 봇별 action dict |
| C→S | EVENT | 이벤트 로그 (kill / pickup / zone 등) |
| C→S | MATCH_END | 최종 순위 + on_episode_done 트리거 |

전체 명세는 [PROTOCOL.md](https://github.com/26-CloudAI/loa-battleroyale-game/blob/main/PROTOCOL.md).

## 현재 한계 (v0.1)
- 단일 매치 / 단일 연결만 지원
- 인증·Redis·DB 적재 없음 (`BattleRoyale` 의 인프라 미사용)
- 봇 종류: HerbivoreBot (초식봇), MadDogBot (미친개봇), CamperBot (존버봇). bot_id 별 매핑은 `ws_server.py BOT_CLASS_BY_ID` 참조.
- choose_spawn 흐름은 클라이언트가 `MATCH_INFO` 를 명시 전송해야 동작
