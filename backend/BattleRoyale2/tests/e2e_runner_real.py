"""M2 E2E (수동): RunnerManager 가 실제 Godot 컨테이너를 spawn → 서버 접속 → 매치 →
프레임 기록 → reaper 정리까지 검증. 자동 단위테스트 아님(도커/서버 필요).

선행: docker 이미지 loa-headless-poc 빌드 + BR2 서버가 8767 에서 실행 중.
실행: python BattleRoyale2/tests/e2e_runner_real.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request

from BattleRoyale2.server.runner_manager import RunnerManager

MATCH = "e2e_real"
PORT = 8767


def spawn(cmd: list[str]) -> subprocess.Popen:
    # cmd = [bin, --main-pack, pck, --, --match=.., --ws=.., --token=.., --quit-on-end]
    user_args = cmd[cmd.index("--") + 1:]
    docker = [
        "docker", "run", "--rm", "--name", "loa-e2e-real",
        "--add-host=host.docker.internal:host-gateway",
        "loa-headless-poc", "godot_server", "--main-pack", "/out/game.pck", "--",
    ] + user_args
    print("[e2e] spawn:", " ".join(docker))
    return subprocess.Popen(docker, stdin=subprocess.DEVNULL)


def replay_count() -> int:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{PORT}/api/games/{MATCH}/replay", timeout=5) as r:
            return json.load(r).get("total_frames", 0)
    except Exception as e:  # noqa: BLE001
        print("[e2e] replay fetch err:", e)
        return -1


def main() -> int:
    exits: list = []
    rm = RunnerManager(
        godot_bin="ignored", game_pck="ignored",
        ws_base=f"ws://host.docker.internal:{PORT}/match/",
        runner_token="secret-e2e",
        match_timeout=240, poll_interval=2.0, spawn_fn=spawn,
    )
    rm.on_exit = lambda mid, rc, reason: exits.append((mid, rc, reason))

    assert rm.try_spawn(MATCH), "spawn 실패"
    print("[e2e] spawned, active=", rm.active_count())

    deadline = time.monotonic() + 230
    last = 0
    while rm.is_active(MATCH) and time.monotonic() < deadline:
        time.sleep(5)
        c = replay_count()
        if c != last:
            print(f"[e2e] frames={c} active={rm.is_active(MATCH)}")
            last = c

    final = replay_count()
    print("=" * 50)
    print(f"[e2e] RESULT: frames={final} still_active={rm.is_active(MATCH)} exits={exits}")
    ok = final > 0 and not rm.is_active(MATCH) and exits == []
    print("[e2e] VERDICT:", "PASS" if ok else "CHECK")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
