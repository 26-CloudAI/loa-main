"""
AI Arena — 서버 설정
Redis, WebSocket, API 관련 설정값.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RedisConfig:
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str | None = None

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
    port: int = 8080

    # 봇 코드 업로드 제한
    max_bot_code_size: int = 50_000     # 50KB
    max_bots_per_game: int = 100

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
