"""
League of Agents — 통합 서버 엔트리포인트

BattleRoyale: /battleroyale  (예: /battleroyale/api/games, /battleroyale/ws/games/...)
MockStocks:   /stocks        (예: /stocks/api/games, /stocks/ws/games/...)

사용법:
    python run_server.py
    python run_server.py --redis
    python run_server.py --port 9000
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

_base = Path(__file__).parent

if (_base / "BattleRoyale").exists():
    # ── 로컬 개발 ────────────────────────────────────────────────────────────
    # 로컬 구조:
    #   BattleRoyale/src/arena/   →  src.arena.*
    #   MockStocks/src/stocks/    →  src.stocks.*
    #   BattleRoyale/bots/        →  bots.camper / bots.herbivore / bots.mad_dog
    #   MockStocks/bots/          →  bots.long_term / bots.short_trader
    #
    # 가상 `src` 패키지: __path__를 두 디렉토리로 설정해 서브패키지를 양쪽에서 검색
    _src_pkg = types.ModuleType("src")
    _src_pkg.__path__ = [
        str(_base / "BattleRoyale" / "src"),
        str(_base / "MockStocks" / "src"),
    ]
    _src_pkg.__package__ = "src"
    sys.modules["src"] = _src_pkg

    _bots_pkg = types.ModuleType("bots")
    _bots_pkg.__path__ = [
        str(_base / "BattleRoyale" / "bots"),
        str(_base / "MockStocks" / "bots"),
    ]
    _bots_pkg.__package__ = "bots"
    sys.modules["bots"] = _bots_pkg

else:
    # ── Docker ───────────────────────────────────────────────────────────────
    # Docker 구조:
    #   /app/src/arena/ + /app/src/stocks/  (Dockerfile에서 병합)
    #   /app/bots/                          (Dockerfile에서 병합)
    #
    # 로컬과 동일하게 가상 패키지로 명시적 경로 설정
    _src_pkg = types.ModuleType("src")
    _src_pkg.__path__ = [str(_base / "src")]
    _src_pkg.__package__ = "src"
    sys.modules["src"] = _src_pkg

    _bots_pkg = types.ModuleType("bots")
    _bots_pkg.__path__ = [str(_base / "bots")]
    _bots_pkg.__package__ = "bots"
    sys.modules["bots"] = _bots_pkg

from src.arena.server import settings
from src.arena.server.logging_config import configure_logging

configure_logging()

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="League of Agents 통합 서버")
    parser.add_argument(
        "--port", type=int, default=settings.SERVER_PORT,
        help=f"포트 (기본: SERVER_PORT 환경변수 또는 {settings.SERVER_PORT})",
    )
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--redis", action="store_true", help="Redis 사용 (기본: 인메모리)")
    parser.add_argument("--redis-host", type=str, default=None)
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--reload", action="store_true", help="개발 모드 (자동 리로드)")
    args = parser.parse_args()

    use_redis = args.redis or settings.USE_REDIS

    try:
        import uvicorn
    except ImportError:
        print("uvicorn이 필요합니다: pip install uvicorn")
        sys.exit(1)

    from fastapi import FastAPI
    from src.arena.server.app import create_app as create_br_app
    from src.arena.server.config import ServerConfig, RedisConfig, APIConfig
    from stocks.server.app import create_app as create_ms_app

    redis_host = args.redis_host or os.environ.get("REDIS_HOST", "localhost")
    redis_cfg = RedisConfig(host=redis_host, port=args.redis_port)
    api_cfg = APIConfig(host=args.host, port=args.port)
    server_cfg = ServerConfig(redis=redis_cfg, api=api_cfg)

    br_app = create_br_app(server_config=server_cfg, use_redis=use_redis)
    ms_app = create_ms_app()

    # 서브앱을 mount()하면 각 앱의 lifespan이 자동 실행되지 않으므로
    # 부모 앱 lifespan에서 명시적으로 호출
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with br_app.router.lifespan_context(br_app):
            async with ms_app.router.lifespan_context(ms_app):
                yield

    app = FastAPI(title="League of Agents", lifespan=lifespan)
    # CORS는 각 서브앱(br_app, ms_app)이 자체 미들웨어로 처리

    app.mount("/battleroyale", br_app)
    app.mount("/stocks", ms_app)

    print("=" * 50)
    print("  League of Agents 통합 서버")
    print(f"  http://{args.host}:{args.port}")
    print(f"  BattleRoyale : /battleroyale")
    print(f"  MockStocks   : /stocks")
    print(f"  Redis: {'활성' if use_redis else '인메모리 (개발 모드)'}")
    print("=" * 50)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
