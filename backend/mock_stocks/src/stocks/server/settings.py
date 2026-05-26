"""
MockStocks — 환경변수 기반 설정

BattleRoyale와 동일한 DB 환경변수를 독립적으로 읽어 같은 ai_arena DB를 공유한다.
"""

import os

# ── 서버 ───────────────────────────────────────
SERVER_PORT: int = int(os.getenv("STOCKS_PORT", "8090"))
JWT_SECRET: str  = os.getenv("JWT_SECRET", "")

# ── DB ─────────────────────────────────────────
DB_TYPE: str     = os.environ.get("DB_TYPE", "sqlite")        # "sqlite" | "postgresql"
DB_HOST: str     = os.environ.get("DB_HOST", "")
DB_NAME: str     = os.environ.get("DB_NAME", "ai_arena")
DB_USER: str     = os.environ.get("DB_USER", "")
DB_PASSWORD: str = os.environ.get("DB_PASSWORD", "")
DB_CONNECT_TIMEOUT: int = int(os.environ.get("DB_CONNECT_TIMEOUT", "10"))
DB_STATEMENT_TIMEOUT_MS: int = int(os.environ.get("DB_STATEMENT_TIMEOUT_MS", "30000"))
DB_LOCK_TIMEOUT_MS: int = int(os.environ.get("DB_LOCK_TIMEOUT_MS", "5000"))
DB_INIT_TIMEOUT_SEC: float = float(os.environ.get("DB_INIT_TIMEOUT_SEC", "35"))
DB_RETRY_INTERVAL_SEC: float = float(os.environ.get("DB_RETRY_INTERVAL_SEC", "10"))

# ── Bot Runner ──────────────────────────────────
BOT_RUNNER_URL: str = os.environ.get("BOT_RUNNER_URL", "")
BOT_RUNNER_TIMEOUT_SEC: float = float(os.environ.get("BOT_RUNNER_TIMEOUT_SEC", "0.5"))
BOT_RUNNER_REQUIRED: bool = os.environ.get("BOT_RUNNER_REQUIRED", "false").lower() in ("true", "1", "yes")
