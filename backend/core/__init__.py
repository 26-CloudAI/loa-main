"""arena_core — 도메인 무관 게임 엔진/타입/유틸.

각 게임(battle_royale, boss_battle, mock_stocks 등)이 공유하는
순수 도메인 모델 + 엔진을 모아둔 패키지.

  - config: GameConfig 데이터 클래스 + DEFAULT_CONFIG 인스턴스
  - types: Action / CellType / Position 등 enum/dataclass
  - bot_interface: 모든 봇이 구현해야 하는 BotInterface
  - grid: 맵 셀/광물 관리
  - zone: 자기장(safe zone) 페이즈/수축 로직
  - vision: 시야 + 리더보드 빌더
  - engine: 게임 루프(틱) 진행자

도메인-bound 로직(인증/DB/세션/룰/UI/GCS)은 절대 import하지 않는다.
"""
