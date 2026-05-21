"""
AI Arena — 서버 설정
Redis, WebSocket, API 관련 설정값.

환경변수로 재정의 가능:
  REDIS_HOST      Redis 서버 주소 (기본: localhost)
  REDIS_PORT      Redis 포트 (기본: 6379)
  REDIS_PASSWORD  Redis 비밀번호 (기본: None)
  API_PORT        API 서버 포트 (기본: 8080)
  MAX_BOT_CODE_SIZE  봇 코드 최대 크기 bytes (기본: 50000)
  MAX_BOTS_PER_GAME  게임당 최대 봇 수 (기본: 100)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RedisConfig:
    host: str = os.environ.get("REDIS_HOST", "localhost")
    port: int = int(os.environ.get("REDIS_PORT", "6379"))
    db: int = 0
    password: str | None = os.environ.get("REDIS_PASSWORD", None)

    # 키 접두사 (네임스페이스 분리)
    key_prefix: str = "arena:"

    # 게임 상태 TTL (초) — 종료된 게임 자동 삭제
    game_state_ttl: int = 3600          # 1시간
    game_result_ttl: int = 86400        # 24시간

    # Pub/Sub 채널 패턴
    tick_channel_prefix: str = "arena:tick:"    # arena:tick:{game_id}
    event_channel_prefix: str = "arena:event:"  # arena:event:{game_id}


@dataclass(frozen=True)
class WebSocketConfig:
    # 클라이언트 연결 제한
    max_connections_per_game: int = 200
    max_total_connections: int = 1000

    # 하트비트
    ping_interval: float = 20.0         # 초
    ping_timeout: float = 10.0

    # 메시지 큐 크기 (느린 클라이언트 보호)
    client_queue_size: int = 50


@dataclass(frozen=True)
class APIConfig:
    host: str = "0.0.0.0"
    port: int = int(os.environ.get("API_PORT", "8080"))

    # 봇 코드 업로드 제한
    max_bot_code_size: int = int(os.environ.get("MAX_BOT_CODE_SIZE", "50000"))   # 50KB
    max_bots_per_game: int = int(os.environ.get("MAX_BOTS_PER_GAME", "100"))

    # 게임 틱 간격 (초) — 관전 속도 제어
    tick_interval: float = 0.05         # 50ms (초당 20틱)
    tick_interval_fast: float = 0.02    # 20ms (초당 50틱)
    tick_interval_slow: float = 0.2     # 200ms (초당 5틱)


@dataclass(frozen=True)
class ServerConfig:
    redis: RedisConfig = field(default_factory=RedisConfig)
    websocket: WebSocketConfig = field(default_factory=WebSocketConfig)
    api: APIConfig = field(default_factory=APIConfig)


DEFAULT_SERVER_CONFIG = ServerConfig()
