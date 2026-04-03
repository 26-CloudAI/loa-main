"""
AI Arena — 로깅 설정

LOG_FORMAT 환경변수에 따라 텍스트 또는 JSON 포맷으로 로깅을 설정한다.
JSON 포맷은 GCP Cloud Logging이 severity 필드로 자동 분류할 수 있도록
필드명을 GCP 스펙에 맞춘다.

사용:
    from src.arena.server.logging_config import configure_logging
    configure_logging()
"""

from __future__ import annotations

import json
import logging
import sys

from . import settings


class _JsonFormatter(logging.Formatter):
    """
    GCP Cloud Logging 호환 JSON 포매터.

    GCP가 인식하는 severity 필드 매핑:
      DEBUG   → DEBUG
      INFO    → INFO
      WARNING → WARNING
      ERROR   → ERROR
    """

    def format(self, record: logging.LogRecord) -> str:
        log: dict = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "logger": record.name,
        }
        if record.exc_info:
            log["exception"] = self.formatException(record.exc_info)
        return json.dumps(log, ensure_ascii=False)


def configure_logging() -> None:
    """
    settings.LOG_FORMAT에 따라 루트 로거를 설정한다.

    LOG_FORMAT=json  → JSON 포맷 (GCP Cloud Logging 호환)
    LOG_FORMAT=text  → 사람이 읽기 쉬운 텍스트 포맷 (기본값)
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)

    if settings.LOG_FORMAT == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
        )

    root.handlers.clear()
    root.addHandler(handler)
