"""
/healthz, /livez 엔드포인트 테스트.

run_server.py는 통합 서버 엔트리포인트이므로 직접 import 대신
FastAPI 앱을 직접 구성해 엔드포인트 로직만 검증한다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))


def _build_test_app(br_db_ok: bool, ms_db_ok: bool) -> FastAPI:
    """br_db_ok / ms_db_ok 상태를 가진 mock sub-app으로 부모 앱을 구성한다."""
    br_app = MagicMock()
    br_app.state.db_ok = lambda: br_db_ok

    ms_app = MagicMock()
    ms_app.state.db_ok = lambda: ms_db_ok

    app = FastAPI()

    @app.get("/healthz")
    async def healthz():
        b = br_app.state.db_ok()
        m = ms_app.state.db_ok()
        status = "ok" if (b and m) else "degraded"
        body = {
            "status": status,
            "battleroyale": {"db": "ok" if b else "error"},
            "stocks": {"db": "ok" if m else "error"},
        }
        return JSONResponse(content=body, status_code=200 if status == "ok" else 503)

    @app.get("/livez")
    async def livez():
        return {"status": "alive"}

    return app


# ── /healthz ──────────────────────────────────────────────────────────────────

def test_healthz_ok_when_both_dbs_up():
    client = TestClient(_build_test_app(br_db_ok=True, ms_db_ok=True))
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["battleroyale"]["db"] == "ok"
    assert body["stocks"]["db"] == "ok"


def test_healthz_degraded_when_br_db_down():
    client = TestClient(_build_test_app(br_db_ok=False, ms_db_ok=True))
    resp = client.get("/healthz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["battleroyale"]["db"] == "error"
    assert body["stocks"]["db"] == "ok"


def test_healthz_degraded_when_ms_db_down():
    client = TestClient(_build_test_app(br_db_ok=True, ms_db_ok=False))
    resp = client.get("/healthz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["battleroyale"]["db"] == "ok"
    assert body["stocks"]["db"] == "error"


def test_healthz_degraded_when_both_dbs_down():
    client = TestClient(_build_test_app(br_db_ok=False, ms_db_ok=False))
    resp = client.get("/healthz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"


# ── /livez ────────────────────────────────────────────────────────────────────

def test_livez_always_200():
    client = TestClient(_build_test_app(br_db_ok=False, ms_db_ok=False))
    resp = client.get("/livez")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}
