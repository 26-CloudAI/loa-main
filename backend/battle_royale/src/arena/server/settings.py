"""
AI Arena — 환경변수 기반 설정

서버 시작 시 환경변수를 읽어 모듈 수준 상수로 노출한다.
설정이 한 곳에 집중되므로 GCP Cloud Run 등 외부 환경에서 env var만으로 제어 가능.

환경변수 목록:
  USE_REDIS       Redis 사용 여부 (기본: false)
  JWT_SECRET      JWT 서명 비밀키 (없으면 랜덤 생성 + 경고)
  LOG_FORMAT      로그 포맷 (기본: text | json)
  SERVER_PORT     서버 포트 (기본: 8080)
  DB_TYPE         DB 종류 (기본: sqlite | postgresql)
  DB_HOST         DB 호스트
  DB_NAME         DB 이름 (기본: ai_arena)
  DB_USER         DB 사용자
  DB_PASSWORD     DB 비밀번호
  DB_CONNECT_TIMEOUT       DB 연결 timeout 초 (기본: 10)
  DB_STATEMENT_TIMEOUT_MS  PostgreSQL statement timeout ms (기본: 30000)
  DB_LOCK_TIMEOUT_MS       PostgreSQL lock timeout ms (기본: 5000)
"""

from __future__ import annotations

import logging
import os
import secrets

logger = logging.getLogger(__name__)

# ── Redis ──────────────────────────────────────
USE_REDIS: bool = os.environ.get("USE_REDIS", "false").lower() in ("true", "1", "yes")

# ── JWT ────────────────────────────────────────
_raw_secret = os.environ.get("JWT_SECRET", "")
if not _raw_secret:
    _raw_secret = secrets.token_hex(32)
    logger.warning(
        "JWT_SECRET 환경변수가 설정되지 않았습니다. "
        "랜덤 시크릿을 사용합니다. "
        "서버 재시작 시 기존 토큰이 무효화됩니다. "
        "프로덕션에서는 JWT_SECRET 환경변수를 설정하세요."
    )
JWT_SECRET: str = _raw_secret

# ── 로깅 ───────────────────────────────────────
LOG_FORMAT: str = os.environ.get("LOG_FORMAT", "text")  # "text" | "json"

# ── 서버 ───────────────────────────────────────
SERVER_PORT: int = int(os.environ.get("SERVER_PORT", "8080"))

# ── CORS ───────────────────────────────────────
# 콤마 구분 문자열 (예: "https://my-app.web.app,https://my-app.firebaseapp.com")
# env var 없으면 개발 편의상 ["*"] 유지.
# env 가 운영 origin 만 지정해도 dev(localhost:5173 / 127.0.0.1:5173)는 항상 허용해
# 같은 백엔드에 대해 dev 프론트가 fetch 할 수 있게 한다. 운영 백엔드에 localhost 접근
# 자체가 불가능하므로 보안 영향 없음.
_DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
_cors_raw = os.environ.get("CORS_ORIGINS", "")
CORS_ORIGINS: list[str] = (
    [o.strip() for o in _cors_raw.split(",") if o.strip()] + _DEV_ORIGINS
    if _cors_raw
    else ["*"]
)

# ── DB ─────────────────────────────────────────
DB_TYPE: str = os.environ.get("DB_TYPE", "sqlite")        # "sqlite" | "postgresql"
DB_HOST: str = os.environ.get("DB_HOST", "")
DB_NAME: str = os.environ.get("DB_NAME", "ai_arena")
DB_USER: str = os.environ.get("DB_USER", "")
DB_PASSWORD: str = os.environ.get("DB_PASSWORD", "")
DB_CONNECT_TIMEOUT: int = int(os.environ.get("DB_CONNECT_TIMEOUT", "10"))
DB_STATEMENT_TIMEOUT_MS: int = int(os.environ.get("DB_STATEMENT_TIMEOUT_MS", "30000"))
DB_LOCK_TIMEOUT_MS: int = int(os.environ.get("DB_LOCK_TIMEOUT_MS", "5000"))

# ── 환경 ────────────────────────────────────────
ENV: str = os.environ.get("ENV", "production")  # "production" | "development"
