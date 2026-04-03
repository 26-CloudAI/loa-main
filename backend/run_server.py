"""
AI Arena — 서버 엔트리포인트

사용법:
    # 기본 (인메모리 모드, Redis 불필요)
    python run_server.py

    # Redis 모드
    python run_server.py --redis

    # 커스텀 포트
    python run_server.py --port 9000

사전 조건:
    pip install fastapi uvicorn
    pip install redis          # --redis 사용 시
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.arena.server import settings  # noqa: E402  (sys.path 설정 이후 import)
from src.arena.server.logging_config import configure_logging  # noqa: E402

configure_logging()

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="AI Arena 서버")
    parser.add_argument(
        "--port", type=int, default=settings.SERVER_PORT,
        help=f"포트 (기본: SERVER_PORT 환경변수 또는 {settings.SERVER_PORT})",
    )
    parser.add_argument("--host", type=str, default="0.0.0.0", help="호스트")
    parser.add_argument("--redis", action="store_true", help="Redis 사용 (기본: 인메모리)")
    parser.add_argument("--redis-host", type=str, default="localhost")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--reload", action="store_true", help="개발 모드 (자동 리로드)")
    args = parser.parse_args()

    # --redis 플래그가 없을 때 USE_REDIS 환경변수를 fallback으로 사용
    use_redis = args.redis or settings.USE_REDIS

    try:
        import uvicorn
    except ImportError:
        print("uvicorn이 필요합니다: pip install uvicorn")
        sys.exit(1)

    try:
        from src.arena.server.app import create_app
    except ImportError as e:
        print(f"fastapi가 필요합니다: pip install fastapi\n{e}")
        sys.exit(1)

    from src.arena.server.config import ServerConfig, RedisConfig, APIConfig

    redis_cfg = RedisConfig(host=args.redis_host, port=args.redis_port)
    api_cfg = APIConfig(host=args.host, port=args.port)
    server_cfg = ServerConfig(redis=redis_cfg, api=api_cfg)

    app = create_app(server_config=server_cfg, use_redis=use_redis)

    print("=" * 50)
    print(f"  AI Arena 서버")
    print(f"  http://{args.host}:{args.port}")
    print(f"  Redis: {'활성' if use_redis else '인메모리 (개발 모드)'}")
    print(f"  API docs: http://localhost:{args.port}/docs")
    print("=" * 50)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
