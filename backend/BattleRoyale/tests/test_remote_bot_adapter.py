"""RemoteBattleRoyaleBotAdapter 테스트 — mock HTTP 서버 기반."""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.arena.sandbox.remote_adapter import RemoteBattleRoyaleBotAdapter


def _make_server(response_body: dict, status: int = 200, delay: float = 0.0):
    """지정된 응답을 반환하는 mock HTTP 서버를 스레드로 실행. (host, port, server) 반환."""
    body_bytes = json.dumps(response_body).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            import time
            if delay:
                time.sleep(delay)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)

        def log_message(self, *args):
            pass  # 테스트 출력 억제

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return "127.0.0.1", port, server


# ── 정상 응답 ──────────────────────────────────────────────────────────────────

def test_normal_action():
    host, port, srv = _make_server({"ok": True, "action": "MOVE_UP"})
    try:
        adapter = RemoteBattleRoyaleBotAdapter(
            bot_id="test_bot",
            code="def action(state): return 'MOVE_UP'",
            runner_url=f"http://{host}:{port}",
        )
        result = adapter.get_action({"tick": 1})
        assert result == "MOVE_UP"
    finally:
        srv.shutdown()


def test_stay_action():
    host, port, srv = _make_server({"ok": True, "action": "STAY"})
    try:
        adapter = RemoteBattleRoyaleBotAdapter(
            bot_id="test_bot",
            code="def action(state): return 'STAY'",
            runner_url=f"http://{host}:{port}",
        )
        result = adapter.get_action({})
        assert result == "STAY"
    finally:
        srv.shutdown()


# ── fallback 케이스 ────────────────────────────────────────────────────────────

def test_timeout_returns_stay():
    host, port, srv = _make_server({"ok": True, "action": "MOVE_UP"}, delay=1.0)
    try:
        adapter = RemoteBattleRoyaleBotAdapter(
            bot_id="test_bot",
            code="def action(state): return 'MOVE_UP'",
            runner_url=f"http://{host}:{port}",
            timeout=0.1,
        )
        result = adapter.get_action({})
        assert result == "STAY"
    finally:
        srv.shutdown()


def test_server_error_returns_stay():
    host, port, srv = _make_server({"error": "internal"}, status=500)
    try:
        adapter = RemoteBattleRoyaleBotAdapter(
            bot_id="test_bot",
            code="def action(state): return 'x'",
            runner_url=f"http://{host}:{port}",
        )
        result = adapter.get_action({})
        assert result == "STAY"
    finally:
        srv.shutdown()


def test_invalid_json_returns_stay():
    class BadHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"not-json!!!")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), BadHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        adapter = RemoteBattleRoyaleBotAdapter(
            bot_id="test_bot",
            code="def action(state): return 'x'",
            runner_url=f"http://127.0.0.1:{port}",
        )
        result = adapter.get_action({})
        assert result == "STAY"
    finally:
        server.shutdown()


def test_action_not_string_returns_stay():
    host, port, srv = _make_server({"ok": True, "action": 123})
    try:
        adapter = RemoteBattleRoyaleBotAdapter(
            bot_id="test_bot",
            code="def action(state): return 123",
            runner_url=f"http://{host}:{port}",
        )
        result = adapter.get_action({})
        assert result == "STAY"
    finally:
        srv.shutdown()


def test_connection_refused_returns_stay():
    adapter = RemoteBattleRoyaleBotAdapter(
        bot_id="test_bot",
        code="def action(state): return 'MOVE_UP'",
        runner_url="http://127.0.0.1:1",  # 닫힌 포트
        timeout=0.5,
    )
    result = adapter.get_action({})
    assert result == "STAY"


# ── code_hash 전송 확인 ────────────────────────────────────────────────────────

def test_code_hash_sent_in_payload():
    import hashlib

    received: list[dict] = []

    class CapturingHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            received.append(body)
            resp = json.dumps({"ok": True, "action": "STAY"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), CapturingHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    code = "def action(state): return 'STAY'"
    expected_hash = "sha256:" + hashlib.sha256(code.encode()).hexdigest()

    try:
        adapter = RemoteBattleRoyaleBotAdapter(
            bot_id="bot1",
            code=code,
            runner_url=f"http://127.0.0.1:{port}",
        )
        adapter.get_action({"tick": 0})
        assert received, "요청이 수신되지 않았습니다."
        assert received[0]["code_hash"] == expected_hash
        assert received[0]["mode"] == "battleroyale"
        assert received[0]["bot_id"] == "bot1"
    finally:
        server.shutdown()
