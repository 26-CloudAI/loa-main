"""BR2 헤드리스 Godot 러너 오케스트레이션 (C2 라이브 관전).

POST /api/games 시 서버에서 헤드리스 Godot 러너(프로세스)를 띄워 게임을
서버사이드로 시뮬레이션한다(브라우저 불필요 → 생성 즉시 'running', 도중 관전 가능).

기본 비활성: 환경변수 BR2_RUNNER_ENABLED=1 이고 바이너리/팩 경로가 있어야 동작.
설정 안 되면 get_runner_manager() 는 None → create_game 동작 불변(기존과 동일).

환경변수:
  BR2_RUNNER_ENABLED       "1" 이면 활성 (기본 비활성)
  BR2_GODOT_BIN            헤드리스 런타임 바이너리 경로 (godot_server)
  BR2_GAME_PCK             export 된 game.pck 경로
  BR2_RUNNER_WS            러너가 접속할 WS 베이스 (끝 /match/)
                          기본 ws://127.0.0.1:8080/battleroyale2/match/
  BR2_RUNNER_SECRET        러너 WS 인증용 공유 시크릿 (WS 핸들러가 동일 값 허용)
  BR2_MAX_CONCURRENT_GAMES 동시 러너 수 상한 (기본 4)
  BR2_MATCH_TIMEOUT_SEC    러너 1판 최대 수명(초). 초과 시 kill (기본 300)
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip())
    except (TypeError, ValueError):
        return default


SpawnFn = Callable[[list[str]], "subprocess.Popen"]
# (match_id, returncode, reason) — 비정상 종료/타임아웃 시 호출 (예: DB abandoned 표시)
ExitCb = Callable[[str, int, str], None]


class RunnerManager:
    """헤드리스 러너 프로세스 생성/추적/정리. 스레드 reaper 로 수명 관리."""

    def __init__(
        self,
        *,
        godot_bin: str,
        game_pck: str,
        ws_base: str,
        runner_token: str,
        max_concurrent: int = 4,
        match_timeout: int = 300,
        poll_interval: float = 2.0,
        spawn_fn: Optional[SpawnFn] = None,
    ) -> None:
        self._godot_bin = godot_bin
        self._game_pck = game_pck
        self._ws_base = ws_base if ws_base.endswith("/") else ws_base + "/"
        self._runner_token = runner_token
        self._max_concurrent = max(1, max_concurrent)
        self._match_timeout = max(10, match_timeout)
        self._poll_interval = poll_interval
        self._spawn_fn = spawn_fn or self._default_spawn
        # match_id -> (proc, started_monotonic)
        self._procs: dict[str, tuple[subprocess.Popen, float]] = {}
        self._lock = threading.Lock()
        self._reaper: Optional[threading.Thread] = None
        self._stopping = False
        self.on_exit: Optional[ExitCb] = None  # 앱이 DB 정리 콜백 주입

    # ---- 커맨드 구성 ----
    def build_cmd(self, match_id: str) -> list[str]:
        return [
            self._godot_bin,
            "--main-pack", self._game_pck,
            "--",  # 이후는 게임(main.gd)이 OS.get_cmdline_args 로 읽는 사용자 인자
            "--match=%s" % match_id,
            "--ws=%s" % self._ws_base,
            "--token=%s" % self._runner_token,
            "--quit-on-end",
        ]

    def _default_spawn(self, cmd: list[str]) -> "subprocess.Popen":
        # 출력은 부모로 흘려보냄(Cloud Run 로그 수집). 입력은 차단.
        return subprocess.Popen(cmd, stdin=subprocess.DEVNULL)

    # ---- 상태 조회 ----
    def active_count(self) -> int:
        with self._lock:
            return len(self._procs)

    def is_active(self, match_id: str) -> bool:
        with self._lock:
            return match_id in self._procs

    # ---- 생성 ----
    def try_spawn(self, match_id: str) -> bool:
        """러너 생성 시도. 성공/이미실행=True, 동시성 초과=False."""
        with self._lock:
            if self._stopping:
                return False
            if match_id in self._procs:
                return True  # 중복 호출 멱등
            if len(self._procs) >= self._max_concurrent:
                logger.warning(
                    "[runner] capacity full (%d/%d) — match=%s 생성 거절",
                    len(self._procs), self._max_concurrent, match_id,
                )
                return False
            try:
                proc = self._spawn_fn(self.build_cmd(match_id))
            except Exception:  # noqa: BLE001
                logger.exception("[runner] spawn 실패 match=%s", match_id)
                return False
            self._procs[match_id] = (proc, time.monotonic())
        logger.info(
            "[runner] spawned match=%s pid=%s (active=%d/%d)",
            match_id, getattr(proc, "pid", "?"), self.active_count(), self._max_concurrent,
        )
        self._ensure_reaper()
        return True

    # ---- 종료 ----
    def stop(self, match_id: str) -> None:
        with self._lock:
            entry = self._procs.pop(match_id, None)
        if entry is not None:
            self._kill(entry[0])

    def stop_all(self) -> None:
        self._stopping = True
        with self._lock:
            entries = list(self._procs.items())
            self._procs.clear()
        for _mid, (proc, _t) in entries:
            self._kill(proc)

    @staticmethod
    def _kill(proc: "subprocess.Popen") -> None:
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    proc.kill()
        except Exception:  # noqa: BLE001
            pass

    # ---- reaper ----
    def _ensure_reaper(self) -> None:
        with self._lock:
            if self._reaper is not None and self._reaper.is_alive():
                return
            self._reaper = threading.Thread(
                target=self._reap_loop, name="br2-runner-reaper", daemon=True)
            self._reaper.start()

    def _reap_loop(self) -> None:
        while True:
            time.sleep(self._poll_interval)
            now = time.monotonic()
            finished: list[tuple[str, int, str]] = []
            with self._lock:
                if not self._procs and not self._stopping:
                    # 더 돌릴 게 없으면 reaper 종료(다음 spawn 때 재기동)
                    self._reaper = None
                    return
                for mid, (proc, started) in list(self._procs.items()):
                    rc = proc.poll()
                    if rc is not None:
                        del self._procs[mid]
                        # rc==0 정상 종료(MATCH_END 후 quit). !=0 비정상.
                        if rc != 0:
                            finished.append((mid, rc, "crash"))
                    elif now - started > self._match_timeout:
                        self._kill(proc)
                        del self._procs[mid]
                        finished.append((mid, -1, "timeout"))
            for mid, rc, reason in finished:
                logger.warning("[runner] match=%s 비정상 종료 rc=%s reason=%s", mid, rc, reason)
                cb = self.on_exit
                if cb is not None:
                    try:
                        cb(mid, rc, reason)
                    except Exception:  # noqa: BLE001
                        logger.exception("[runner] on_exit 콜백 실패 match=%s", mid)


# ---- 모듈 싱글턴 ----
_MANAGER: Optional[RunnerManager] = None
_TRIED = False


def get_runner_manager() -> Optional[RunnerManager]:
    """환경변수 기반 싱글턴. 비활성/미설정 시 None."""
    global _MANAGER, _TRIED
    if _TRIED:
        return _MANAGER
    _TRIED = True
    if not _env_bool("BR2_RUNNER_ENABLED", False):
        logger.info("[runner] 비활성 (BR2_RUNNER_ENABLED!=1)")
        return None
    godot_bin = os.environ.get("BR2_GODOT_BIN", "").strip()
    game_pck = os.environ.get("BR2_GAME_PCK", "").strip()
    if not godot_bin or not game_pck:
        logger.warning("[runner] BR2_GODOT_BIN / BR2_GAME_PCK 미설정 — 러너 비활성")
        return None
    _MANAGER = RunnerManager(
        godot_bin=godot_bin,
        game_pck=game_pck,
        ws_base=os.environ.get("BR2_RUNNER_WS", "ws://127.0.0.1:8080/battleroyale2/match/"),
        runner_token=os.environ.get("BR2_RUNNER_SECRET", ""),
        max_concurrent=_env_int("BR2_MAX_CONCURRENT_GAMES", 4),
        match_timeout=_env_int("BR2_MATCH_TIMEOUT_SEC", 300),
    )
    logger.info(
        "[runner] 활성 bin=%s pck=%s ws=%s max=%d",
        godot_bin, game_pck, _MANAGER._ws_base, _MANAGER._max_concurrent,
    )
    return _MANAGER
