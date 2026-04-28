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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


def main():
    parser = argparse.ArgumentParser(description="AI Arena 서버")
    parser.add_argument("--port", type=int, default=8080, help="포트 (기본 8080)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="호스트")
    parser.add_argument("--redis", action="store_true", help="Redis 사용 (기본: 인메모리)")
    parser.add_argument("--redis-host", type=str, default="localhost")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--reload", action="store_true", help="개발 모드 (자동 리로드)")
    args = parser.parse_args()

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

    app = create_app(server_config=server_cfg, use_redis=args.redis)

    print("=" * 50)
    print(f"  AI Arena 서버")
    print(f"  http://{args.host}:{args.port}")
    print(f"  Redis: {'활성' if args.redis else '인메모리 (개발 모드)'}")
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
