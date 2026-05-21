"""RemoteStockBotAdapter 테스트 — mock HTTP 서버 기반."""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.stocks.sandbox.remote_adapter import RemoteStockBotAdapter


def _make_server(response_body: dict, status: int = 200, delay: float = 0.0):
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
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return "127.0.0.1", port, server


# ── 정상 응답 ──────────────────────────────────────────────────────────────────

def test_buy_action():
    host, port, srv = _make_server({
        "ok": True,
        "action": {"action": "BUY", "symbol": "APEX", "quantity": 10},
    })
    try:
        adapter = RemoteStockBotAdapter(
            bot_id="stock_bot",
            code="def action(state): return {'action':'BUY','symbol':'APEX','quantity':10}",
            runner_url=f"http://{host}:{port}",
        )
        result = adapter.get_action({"market": {}, "my_bot": {}})
        assert result == {"action": "BUY", "symbol": "APEX", "quantity": 10}
    finally:
        srv.shutdown()


def test_hold_action():
    host, port, srv = _make_server({"ok": True, "action": {"action": "HOLD"}})
    try:
        adapter = RemoteStockBotAdapter(
            bot_id="stock_bot",
            code="def action(state): return {'action':'HOLD'}",
            runner_url=f"http://{host}:{port}",
        )
        result = adapter.get_action({})
        assert result == {"action": "HOLD"}
    finally:
        srv.shutdown()


# ── fallback 케이스 ────────────────────────────────────────────────────────────

def test_timeout_returns_hold():
    host, port, srv = _make_server({"ok": True, "action": {"action": "BUY"}}, delay=1.0)
    try:
        adapter = RemoteStockBotAdapter(
            bot_id="stock_bot",
            code="def action(state): pass",
            runner_url=f"http://{host}:{port}",
            timeout=0.1,
        )
        result = adapter.get_action({})
        assert result == {"action": "HOLD"}
    finally:
        srv.shutdown()


def test_server_error_returns_hold():
    host, port, srv = _make_server({"error": "oops"}, status=500)
    try:
        adapter = RemoteStockBotAdapter(
            bot_id="stock_bot",
            code="def action(state): pass",
            runner_url=f"http://{host}:{port}",
        )
        result = adapter.get_action({})
        assert result == {"action": "HOLD"}
    finally:
        srv.shutdown()


def test_action_not_dict_returns_hold():
    host, port, srv = _make_server({"ok": True, "action": "BUY"})
    try:
        adapter = RemoteStockBotAdapter(
            bot_id="stock_bot",
            code="def action(state): return 'BUY'",
            runner_url=f"http://{host}:{port}",
        )
        result = adapter.get_action({})
        assert result == {"action": "HOLD"}
    finally:
        srv.shutdown()


def test_connection_refused_returns_hold():
    adapter = RemoteStockBotAdapter(
        bot_id="stock_bot",
        code="def action(state): pass",
        runner_url="http://127.0.0.1:1",
        timeout=0.5,
    )
    result = adapter.get_action({})
    assert result == {"action": "HOLD"}


# ── code_hash + mode 확인 ──────────────────────────────────────────────────────

def test_code_hash_and_mode_sent():
    import hashlib

    received: list[dict] = []

    class CapturingHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            received.append(json.loads(self.rfile.read(length)))
            resp = json.dumps({"ok": True, "action": {"action": "HOLD"}}).encode()
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

    code = "def action(state): return {'action':'HOLD'}"
    expected_hash = "sha256:" + hashlib.sha256(code.encode()).hexdigest()

    try:
        adapter = RemoteStockBotAdapter(
            bot_id="sbot",
            code=code,
            runner_url=f"http://127.0.0.1:{port}",
        )
        adapter.get_action({})
        assert received[0]["code_hash"] == expected_hash
        assert received[0]["mode"] == "mockstocks"
        assert received[0]["bot_id"] == "sbot"
    finally:
        server.shutdown()
