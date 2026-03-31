"""
AI Arena — 컨테이너 내부 봇 래퍼

이 스크립트는 Docker 컨테이너 내부에서 실행된다.
유저의 action(state) 함수를 import하여 HTTP API로 노출한다.

의존성: Python 표준 라이브러리만 사용 (pip install 없음).

엔드포인트:
  GET  /health  → {"status": "ok"}
  POST /action  → {"action": "MOVE_UP"} 또는 {"action": "STAY", "error": "..."}
"""

import importlib.util
import json
import sys
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── 유저 봇 모듈 로드 ──

BOT_MODULE_PATH = "/bot/user_bot.py"
VALID_ACTIONS = frozenset([
    "STAY", "MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT",
    "MINE", "ATTACK_UP", "ATTACK_DOWN", "ATTACK_LEFT", "ATTACK_RIGHT",
    "SHIELD",
])

_user_action_fn = None
_load_error = None

try:
    spec = importlib.util.spec_from_file_location("user_bot", BOT_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"모듈을 찾을 수 없습니다: {BOT_MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "action"):
        raise AttributeError("action(state) 함수가 정의되어 있지 않습니다.")
    if not callable(module.action):
        raise TypeError("action은 호출 가능한 함수여야 합니다.")

    _user_action_fn = module.action
except Exception as e:
    _load_error = f"{type(e).__name__}: {e}"
    print(f"[WRAPPER] 봇 로드 실패: {_load_error}", file=sys.stderr)


# ── HTTP 핸들러 ──

class BotHandler(BaseHTTPRequestHandler):
    """봇 액션 요청을 처리하는 HTTP 핸들러."""

    # 로그 억제 (성능 + 클린 출력)
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/health":
            self._respond_json(200, {
                "status": "ok" if _load_error is None else "error",
                "error": _load_error,
            })
        else:
            self._respond_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path != "/action":
            self._respond_json(404, {"error": "Not found"})
            return

        # 봇 로드 실패 시 STAY 반환
        if _user_action_fn is None:
            self._respond_json(200, {
                "action": "STAY",
                "error": _load_error or "봇 함수 미로드",
            })
            return

        try:
            # 요청 본문 파싱
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length)
            state = json.loads(raw_body)

            # 유저 함수 호출
            result = _user_action_fn(state)

            # 반환값 검증
            if not isinstance(result, str):
                result = str(result)
            if result not in VALID_ACTIONS:
                self._respond_json(200, {
                    "action": "STAY",
                    "error": f"유효하지 않은 행동: {result}",
                })
                return

            self._respond_json(200, {"action": result})

        except json.JSONDecodeError as e:
            self._respond_json(400, {
                "action": "STAY",
                "error": f"JSON 파싱 실패: {e}",
            })
        except Exception:
            tb = traceback.format_exc()
            self._respond_json(200, {
                "action": "STAY",
                "error": f"봇 실행 오류:\n{tb}",
            })

    def _respond_json(self, status: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ── 서버 기동 ──

def main():
    port = 8000
    server = HTTPServer(("0.0.0.0", port), BotHandler)
    print(f"[WRAPPER] 봇 서버 시작 (port={port})", file=sys.stderr)
    if _load_error:
        print(f"[WRAPPER] ⚠ 봇 로드 실패 상태로 실행 중", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
