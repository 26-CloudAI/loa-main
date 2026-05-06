"""
MockStocks — 서버 실행 진입점

사용법:
    python run_server.py
    python run_server.py --port 8090
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.stocks.server.settings import SERVER_PORT


def main():
    parser = argparse.ArgumentParser(description="MockStocks 서버")
    parser.add_argument("--port", type=int, default=SERVER_PORT)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("uvicorn이 필요합니다: pip install uvicorn")
        sys.exit(1)

    from src.stocks.server.app import create_app

    app = create_app()

    print("=" * 50)
    print("  MockStocks 서버")
    print(f"  http://{args.host}:{args.port}")
    print(f"  API docs: http://localhost:{args.port}/docs")
    print("=" * 50)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
