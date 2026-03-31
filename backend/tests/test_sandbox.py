"""
AI Arena — 샌드박스 단위 테스트 (Docker 불필요)

Docker 데몬 없이 실행 가능한 테스트:
  1. 래퍼 템플릿의 HTTP 핸들러 로직
  2. DockerBotAdapter의 에러 핸들링
  3. SandboxConfig 검증
"""

import json
import sys
import threading
import time
import unittest
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.arena.sandbox.config import SandboxConfig, DEFAULT_SANDBOX_CONFIG
from src.arena.sandbox.docker_adapter import DockerBotAdapter


# ──────────────────────────────────────────────
#  1. SandboxConfig 테스트
# ──────────────────────────────────────────────

class TestSandboxConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = DEFAULT_SANDBOX_CONFIG
        self.assertEqual(cfg.cpu_quota, 100_000_000)
        self.assertEqual(cfg.mem_limit, "50m")
        self.assertEqual(cfg.container_port, 8000)
        self.assertAlmostEqual(cfg.action_timeout_sec, 0.1)

    def test_cap_drop_default(self):
        cfg = SandboxConfig()
        self.assertEqual(cfg.cap_drop, ["ALL"])

    def test_frozen(self):
        cfg = SandboxConfig()
        with self.assertRaises(AttributeError):
            cfg.cpu_quota = 999

    def test_custom_values(self):
        cfg = SandboxConfig(
            cpu_quota=200_000_000,
            mem_limit="100m",
            action_timeout_sec=0.5,
        )
        self.assertEqual(cfg.cpu_quota, 200_000_000)
        self.assertEqual(cfg.mem_limit, "100m")
        self.assertAlmostEqual(cfg.action_timeout_sec, 0.5)


# ──────────────────────────────────────────────
#  2. DockerBotAdapter 테스트 (모킹된 HTTP 서버 사용)
# ──────────────────────────────────────────────

class MockBotHandler(BaseHTTPRequestHandler):
    """테스트용 모의 봇 HTTP 서버."""

    # 클래스 변수로 동작 제어
    response_action = "MOVE_UP"
    response_delay = 0.0
    should_crash = False

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        if self.path != "/action":
            self.send_response(404)
            self.end_headers()
            return

        if self.should_crash:
            # 연결 즉시 끊기
            self.wfile.close()
            return

        # 지연 시뮬레이션
        if self.response_delay > 0:
            time.sleep(self.response_delay)

        content_length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(content_length)

        body = json.dumps({"action": self.response_action}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _start_mock_server(handler_class, port=0):
    """모의 서버를 백그라운드 스레드로 시작. (port, server) 반환."""
    server = HTTPServer(("127.0.0.1", port), handler_class)
    actual_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return actual_port, server


class TestDockerBotAdapter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 정상 응답 서버
        MockBotHandler.response_action = "MOVE_UP"
        MockBotHandler.response_delay = 0.0
        MockBotHandler.should_crash = False
        cls.port, cls.server = _start_mock_server(MockBotHandler)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def _make_adapter(self, timeout=1.0, port=None):
        cfg = SandboxConfig(action_timeout_sec=timeout)
        p = port or self.port
        return DockerBotAdapter(
            bot_id="test_bot",
            action_url=f"http://127.0.0.1:{p}/action",
            config=cfg,
        )

    def test_normal_response(self):
        MockBotHandler.response_action = "MOVE_UP"
        MockBotHandler.response_delay = 0.0
        MockBotHandler.should_crash = False

        adapter = self._make_adapter()
        state = {"tick": 0, "my_bot": {"id": "test"}}
        result = adapter.get_action(state)

        self.assertEqual(result, "MOVE_UP")
        self.assertEqual(adapter.total_calls, 1)
        self.assertEqual(adapter.timeout_count, 0)
        self.assertEqual(adapter.error_count, 0)

    def test_various_actions(self):
        adapter = self._make_adapter()
        state = {"tick": 0}

        for action in ["STAY", "MINE", "SHIELD", "ATTACK_LEFT"]:
            MockBotHandler.response_action = action
            result = adapter.get_action(state)
            self.assertEqual(result, action)

    def test_connection_refused_returns_stay(self):
        """존재하지 않는 포트 → STAY."""
        adapter = self._make_adapter(timeout=0.5, port=19999)
        result = adapter.get_action({"tick": 0})
        self.assertEqual(result, "STAY")
        self.assertEqual(adapter.error_count, 1)

    def test_bot_id_property(self):
        adapter = self._make_adapter()
        self.assertEqual(adapter.bot_id, "test_bot")

    def test_stats(self):
        adapter = self._make_adapter()
        MockBotHandler.response_action = "MINE"
        MockBotHandler.response_delay = 0.0
        MockBotHandler.should_crash = False

        for _ in range(5):
            adapter.get_action({"tick": 0})

        stats = adapter.get_stats()
        self.assertEqual(stats["bot_id"], "test_bot")
        self.assertEqual(stats["total_calls"], 5)
        self.assertAlmostEqual(stats["success_rate"], 1.0)


class TestDockerBotAdapterTimeout(unittest.TestCase):
    """타임아웃 테스트를 위한 별도 서버."""

    @classmethod
    def setUpClass(cls):
        # 느린 응답 서버
        class SlowHandler(MockBotHandler):
            response_delay = 0.5  # 500ms 지연

        cls.port, cls.server = _start_mock_server(SlowHandler)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_timeout_returns_stay(self):
        """100ms 타임아웃 + 500ms 지연 서버 → STAY."""
        cfg = SandboxConfig(action_timeout_sec=0.1)
        adapter = DockerBotAdapter(
            bot_id="slow_bot",
            action_url=f"http://127.0.0.1:{self.port}/action",
            config=cfg,
        )

        result = adapter.get_action({"tick": 0})
        self.assertEqual(result, "STAY")
        self.assertEqual(adapter.timeout_count, 1)


# ──────────────────────────────────────────────
#  3. 래퍼 템플릿 검증 (코드 레벨)
# ──────────────────────────────────────────────

class TestWrapperTemplate(unittest.TestCase):
    """래퍼 스크립트의 유효성 확인."""

    def test_wrapper_file_exists(self):
        wrapper_path = Path(__file__).parent.parent / "src" / "arena" / "sandbox" / "wrapper_template.py"
        self.assertTrue(wrapper_path.exists(), f"래퍼 파일 누락: {wrapper_path}")

    def test_wrapper_syntax_valid(self):
        """래퍼 코드의 문법 오류 확인."""
        wrapper_path = Path(__file__).parent.parent / "src" / "arena" / "sandbox" / "wrapper_template.py"
        code = wrapper_path.read_text(encoding="utf-8")
        # 컴파일 가능한지 확인 (실행하지 않음)
        compile(code, str(wrapper_path), "exec")

    def test_valid_actions_complete(self):
        """래퍼에 정의된 VALID_ACTIONS가 엔진의 Action enum과 일치."""
        from src.arena.types import Action
        engine_actions = {a.value for a in Action}

        wrapper_path = Path(__file__).parent.parent / "src" / "arena" / "sandbox" / "wrapper_template.py"
        code = wrapper_path.read_text(encoding="utf-8")

        # VALID_ACTIONS 블록 추출 (frozenset 전체)
        start = code.index("VALID_ACTIONS = frozenset(")
        # 닫는 괄호까지 찾기
        depth = 0
        end = start
        for i, ch in enumerate(code[start:], start):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        snippet = code[start:end]
        local_ns = {}
        exec(snippet, {}, local_ns)

        wrapper_actions = local_ns.get("VALID_ACTIONS")
        self.assertIsNotNone(wrapper_actions, "래퍼에서 VALID_ACTIONS를 찾을 수 없음")
        self.assertEqual(engine_actions, set(wrapper_actions))


if __name__ == "__main__":
    unittest.main(verbosity=2)
