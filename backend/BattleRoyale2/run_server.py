"""BattleRoyale2 WS 서버 엔트리포인트.

사용:
    cd loa-backend/backend
    python -m BattleRoyale2.run_server --port 8765

또는:
    uvicorn BattleRoyale2.server.ws_server:app --port 8765
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# loa-backend/backend 를 sys.path 에 추가 → "from BattleRoyale2.xxx" import 가능
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="BattleRoyale2 WS Server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    import uvicorn
    uvicorn.run(
        "BattleRoyale2.server.ws_server:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
