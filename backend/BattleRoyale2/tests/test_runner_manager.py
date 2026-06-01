"""RunnerManager 오케스트레이션 로직 테스트 (스텁 프로세스 사용 — 실제 Godot 불필요).

검증: 커맨드 구성 / 동시성 상한 / 멱등 spawn / 정상·비정상·타임아웃 reaper + on_exit 콜백.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time

from BattleRoyale2.server.runner_manager import RunnerManager


def _mk(spawn_fn, **kw) -> RunnerManager:
    return RunnerManager(
        godot_bin="/fake/godot_server",
        game_pck="/fake/game.pck",
        ws_base="ws://127.0.0.1:8080/battleroyale2/match",  # 끝 슬래시 없음 → 자동 보정 확인
        runner_token="secret123",
        poll_interval=0.2,
        spawn_fn=spawn_fn,
        **kw,
    )


def _py(code: str) -> "subprocess.Popen":
    return subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.DEVNULL)


def test_build_cmd_and_ws_slash():
    rm = _mk(spawn_fn=lambda cmd: None)  # spawn_fn 미사용
    cmd = rm.build_cmd("abc")
    assert cmd[0] == "/fake/godot_server"
    assert "--main-pack" in cmd and "/fake/game.pck" in cmd
    assert "--match=abc" in cmd
    # ws_base 끝 슬래시 자동 보정
    assert "--ws=ws://127.0.0.1:8080/battleroyale2/match/" in cmd
    assert "--token=secret123" in cmd
    assert "--quit-on-end" in cmd
    # '--' 구분자 뒤에 사용자 인자가 와야 함
    assert cmd.index("--") < cmd.index("--match=abc")


def test_concurrency_cap_and_idempotent():
    spawned: list[list[str]] = []

    def spawn(cmd):
        spawned.append(cmd)
        return _py("import time; time.sleep(30)")  # 오래 사는 프로세스

    rm = _mk(spawn_fn=spawn, max_concurrent=2)
    try:
        assert rm.try_spawn("g1") is True
        assert rm.try_spawn("g1") is True   # 멱등 — 재생성 안 함
        assert rm.active_count() == 1
        assert rm.try_spawn("g2") is True
        assert rm.active_count() == 2
        assert rm.try_spawn("g3") is False  # 상한 초과 거절
        assert rm.active_count() == 2
        assert len(spawned) == 2            # 실제 spawn 은 2번만
    finally:
        rm.stop_all()


def test_reaper_normal_exit_no_callback():
    calls: list[tuple] = []
    rm = _mk(spawn_fn=lambda cmd: _py("import sys; sys.exit(0)"))
    rm.on_exit = lambda mid, rc, reason: calls.append((mid, rc, reason))
    rm.try_spawn("ok")
    # reaper 가 정상종료(rc=0) 감지 → 추적 해제, on_exit 호출 안 함
    deadline = time.monotonic() + 5
    while rm.is_active("ok") and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not rm.is_active("ok")
    time.sleep(0.4)
    assert calls == []  # 정상 종료엔 콜백 없음


def test_reaper_crash_calls_callback():
    done = threading.Event()
    captured: list[tuple] = []

    def cb(mid, rc, reason):
        captured.append((mid, rc, reason))
        done.set()

    rm = _mk(spawn_fn=lambda cmd: _py("import sys; sys.exit(3)"))
    rm.on_exit = cb
    rm.try_spawn("boom")
    assert done.wait(5), "비정상 종료 콜백이 호출돼야 함"
    mid, rc, reason = captured[0]
    assert mid == "boom" and rc == 3 and reason == "crash"
    assert not rm.is_active("boom")


def test_reaper_timeout_kills():
    done = threading.Event()
    captured: list[tuple] = []

    def cb(mid, rc, reason):
        captured.append((mid, rc, reason))
        done.set()

    rm = _mk(spawn_fn=lambda cmd: _py("import time; time.sleep(30)"), match_timeout=10)
    # match_timeout 은 최소 10초로 클램프됨 → 테스트용으로 내부 값 직접 낮춤
    rm._match_timeout = 1
    rm.on_exit = cb
    rm.try_spawn("slow")
    assert done.wait(6), "타임아웃 시 kill + 콜백이 호출돼야 함"
    mid, rc, reason = captured[0]
    assert mid == "slow" and reason == "timeout"
    assert not rm.is_active("slow")
