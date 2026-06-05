"""멀티 인스턴스 E2E (수동): Redis 기반 관전 릴레이 + 권위 선출이 인스턴스를 넘어
동작하는지 검증. 자동 단위테스트 아님(실행 중인 Redis 필요).

검증 시나리오:
  - 서버 인스턴스 2개(A:8771, B:8772)를 같은 Redis 로 띄운다.
  - "러너"(권위) WS 를 A 에 연결 → FRAME_INIT/FRAME/MATCH_END 송신(시뮬 기록).
  - "관전자" WS 를 B 에 연결 → ROLE=spectator + catch-up + live + MATCH_END 수신 확인.
    (A 가 Redis 채널에 발행 → B 가 구독해 중계 = Phase 2)
  - 두 번째 eligible 연결이 권위가 못 됨 = 매치당 권위 단 하나 (Phase 3, Redis SET NX).

선행:
  - Redis 실행 중 (기본 localhost:6379). REDIS_HOST/REDIS_PORT 로 변경 가능.
  - 의존성: redis, websockets, uvicorn (uvicorn[standard] 에 포함).
실행:
  cd backend && python BattleRoyale2/tests/e2e_multi_instance.py
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]   # .../backend
# 매 실행마다 고유 match_id — Redis 는 프레임을 영속하므로(Phase 1) 같은 id 재사용 시
# 이전 실행 프레임이 누적돼 catch-up 에 섞인다. 실행별 격리를 위해 uuid 사용.
MATCH = "e2e_multi_" + uuid.uuid4().hex[:8]
PORT_A = 8771
PORT_B = 8772


def _server_env() -> dict:
    env = dict(os.environ)
    env["USE_REDIS"] = "true"
    env.setdefault("REDIS_HOST", "localhost")
    env.setdefault("REDIS_PORT", "6379")
    env["BR2_RUNNER_ENABLED"] = "0"      # 러너 매니저 비활성 — WS 로 직접 러너 역할 수행
    env["DB_TYPE"] = "sqlite"            # 데모 매치(DB game 없음) → 토큰 불필요
    # battle_royale 의 src.arena.* 를 import 가능하게
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_BACKEND), str(_BACKEND / "battle_royale"), env.get("PYTHONPATH", "")]
    )
    return env


def _spawn_server(port: int, env: dict) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "uvicorn",
           "BattleRoyale2.server.ws_server:app", "--port", str(port), "--log-level", "warning"]
    print(f"[e2e] start server :{port}")
    return subprocess.Popen(cmd, cwd=str(_BACKEND), env=env)


def _wait_health(port: int, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return False


async def _run_ws_check() -> bool:
    import websockets  # type: ignore

    url_a = f"ws://127.0.0.1:{PORT_A}/match/{MATCH}"
    url_b = f"ws://127.0.0.1:{PORT_B}/match/{MATCH}"

    # 1) 러너(권위) → 인스턴스 A. HELLO 없이 바로 프레임 기록(권위 경로).
    async with websockets.connect(url_a) as runner:
        await runner.send(json.dumps({"type": "FRAME_INIT",
                                      "data": {"map_size": [10, 10], "coins": [{"id": 1, "pos": [1, 1]}]}}))
        await runner.send(json.dumps({"type": "FRAME", "tick": 1, "data": {"time": 0.1}}))
        await asyncio.sleep(0.3)   # A 가 Redis 에 기록/발행할 시간

        # 2) 관전자 → 인스턴스 B (다른 프로세스!). catch-up + live 를 Redis 경유로 받아야 함.
        async with websockets.connect(url_b) as spec:
            await spec.send(json.dumps({"type": "HELLO", "data": {"version": _proto()}}))

            got: list[dict] = []

            async def _drain(timeout: float = 2.0):
                """더 안 올 때까지 수신해 got 에 누적."""
                try:
                    while True:
                        raw = await asyncio.wait_for(spec.recv(), timeout=timeout)
                        m = json.loads(raw)
                        print("[e2e][recv]", m.get("type"), m.get("tick", ""))
                        got.append(m)
                except asyncio.TimeoutError:
                    pass

            # ROLE + catch-up(FRAME_INIT, FRAME tick1) 을 Redis 에서 읽어 전달
            await _drain()
            # 3) live tail: A 가 새 프레임 → B 관전자에게 Redis 경유 중계
            await runner.send(json.dumps({"type": "FRAME", "tick": 2, "data": {"time": 0.2}}))
            await asyncio.sleep(0.2)
            # 4) MATCH_END 크로스 인스턴스 중계
            await runner.send(json.dumps({"type": "MATCH_END", "data": {"reason": "last_standing"}}))
            await _drain()

    # 정확히-한-번 전달 검증(중복/누락 없음) — 깨끗한 신규 match 기준
    roles = [m for m in got if m["type"] == "ROLE"]
    inits = [m for m in got if m["type"] == "FRAME_INIT"]
    f1 = [m for m in got if m["type"] == "FRAME" and m.get("tick") == 1]
    f2 = [m for m in got if m["type"] == "FRAME" and m.get("tick") == 2]
    ends = [m for m in got if m["type"] == "MATCH_END"]
    assert len(roles) == 1 and roles[0]["data"]["role"] == "spectator", f"ROLE: {got}"
    assert len(inits) == 1, f"FRAME_INIT 정확히 1회여야 (중복/누락): {got}"
    assert len(f1) == 1, f"FRAME tick1 정확히 1회여야: {got}"
    assert len(f2) == 1, f"FRAME tick2(live) 정확히 1회여야: {got}"
    assert len(ends) == 1, f"MATCH_END 정확히 1회여야: {got}"
    assert inits[0]["data"]["coins"][0]["id"] == 1, f"FRAME_INIT 본문 손상: {inits[0]}"

    print("[e2e] [OK] 크로스 인스턴스 관전 중계 — catch-up/live/end 정확히-한-번 통과")
    return True


def _proto() -> str:
    # 서버와 동일한 PROTOCOL_VERSION 사용 (HELLO 버전 일치 필요)
    sys.path.insert(0, str(_BACKEND))
    from BattleRoyale2.server.ws_server import PROTOCOL_VERSION  # type: ignore
    return PROTOCOL_VERSION


def main() -> int:
    # Windows 콘솔(cp949)에서도 한글/기호 출력이 깨지지 않게 utf-8 강제
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    env = _server_env()
    a = _spawn_server(PORT_A, env)
    b = _spawn_server(PORT_B, env)
    try:
        if not (_wait_health(PORT_A) and _wait_health(PORT_B)):
            print("[e2e] [FAIL] 서버 기동 실패 (Redis 미실행/포트 충돌 확인)")
            return 1
        ok = asyncio.run(_run_ws_check())
        return 0 if ok else 1
    except AssertionError as e:
        print(f"[e2e] [FAIL] 검증 실패: {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"[e2e] [FAIL] 오류: {e}")
        return 1
    finally:
        for p in (a, b):
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                p.kill()


if __name__ == "__main__":
    raise SystemExit(main())
