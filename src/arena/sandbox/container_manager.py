"""
AI Arena — Docker 컨테이너 매니저

단일 봇 컨테이너의 전체 라이프사이클을 관리한다.
  생성 → 기동 → 헬스체크 → (게임 중 HTTP 통신) → 정지 → 삭제

의존성: docker (pip install docker)
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

try:
    import docker
    from docker.errors import (
        APIError,
        ContainerError,
        ImageNotFound,
        NotFound,
    )
    from docker.models.containers import Container
    from docker.models.networks import Network

    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False

from .config import SandboxConfig

logger = logging.getLogger(__name__)

# 래퍼 스크립트 경로
_WRAPPER_PATH = Path(__file__).parent / "wrapper_template.py"


class ContainerManager:
    """
    Docker 컨테이너의 라이프사이클을 관리한다.

    하나의 ContainerManager 인스턴스 = 하나의 봇 컨테이너.
    """

    def __init__(
        self,
        bot_id: str,
        bot_code: str,
        config: SandboxConfig,
        client: Optional[object] = None,
    ):
        if not DOCKER_AVAILABLE:
            raise RuntimeError(
                "docker 패키지가 설치되지 않았습니다. "
                "'pip install docker'를 실행하세요."
            )

        self.bot_id = bot_id
        self.bot_code = bot_code
        self.config = config
        self.client: docker.DockerClient = client or docker.from_env()

        self._container: Optional[Container] = None
        self._container_ip: Optional[str] = None
        self._temp_dir: Optional[tempfile.TemporaryDirectory] = None

    @property
    def container_ip(self) -> Optional[str]:
        return self._container_ip

    @property
    def action_url(self) -> Optional[str]:
        if self._container_ip is None:
            return None
        return f"http://{self._container_ip}:{self.config.container_port}/action"

    @property
    def health_url(self) -> Optional[str]:
        if self._container_ip is None:
            return None
        return f"http://{self._container_ip}:{self.config.container_port}/health"

    @property
    def container_name(self) -> str:
        # Docker 컨테이너 이름에 허용되지 않는 문자 치환
        safe_id = self.bot_id.replace(" ", "_")
        return f"{self.config.container_prefix}{safe_id}"

    # ──────────────────────────────────────────────
    #  라이프사이클
    # ──────────────────────────────────────────────

    def create_and_start(self, network: Network) -> str:
        """
        컨테이너를 생성하고 시작한 뒤, 헬스체크가 통과할 때까지 대기.
        반환값: 컨테이너 IP 주소.
        """
        self._prepare_bot_files()
        self._ensure_image()
        self._create_container(network)
        self._start_container()
        self._wait_for_healthy()

        assert self._container_ip is not None
        return self._container_ip

    def stop_and_remove(self) -> None:
        """컨테이너를 정지하고 삭제한다. 임시 파일도 정리."""
        if self._container is not None:
            try:
                self._container.stop(timeout=2)
            except Exception:
                logger.debug("컨테이너 정지 중 오류 (무시)", exc_info=True)

            try:
                self._container.remove(force=True)
            except Exception:
                logger.debug("컨테이너 삭제 중 오류 (무시)", exc_info=True)

            self._container = None
            self._container_ip = None

        if self._temp_dir is not None:
            try:
                self._temp_dir.cleanup()
            except Exception:
                pass
            self._temp_dir = None

    # ──────────────────────────────────────────────
    #  내부 — 파일 준비
    # ──────────────────────────────────────────────

    def _prepare_bot_files(self) -> None:
        """봇 코드와 래퍼 스크립트를 임시 디렉토리에 저장."""
        self._temp_dir = tempfile.TemporaryDirectory(prefix=f"arena-{self.bot_id}-")
        bot_dir = Path(self._temp_dir.name)

        # 유저 봇 코드
        user_bot_path = bot_dir / "user_bot.py"
        user_bot_path.write_text(self.bot_code, encoding="utf-8")

        # 래퍼 스크립트
        wrapper_dest = bot_dir / "wrapper.py"
        wrapper_dest.write_text(_WRAPPER_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    def _ensure_image(self) -> None:
        """베이스 이미지가 로컬에 있는지 확인. 없으면 pull."""
        try:
            self.client.images.get(self.config.base_image)
        except ImageNotFound:
            logger.info("이미지 %s 를 pull 합니다...", self.config.base_image)
            self.client.images.pull(self.config.base_image)

    # ──────────────────────────────────────────────
    #  내부 — 컨테이너 생성/시작
    # ──────────────────────────────────────────────

    def _create_container(self, network: Network) -> None:
        """리소스 제한이 적용된 컨테이너를 생성한다."""
        assert self._temp_dir is not None
        bot_dir = self._temp_dir.name

        self._container = self.client.containers.create(
            image=self.config.base_image,
            name=self.container_name,
            command=["python", "/bot/wrapper.py"],

            # 볼륨 마운트: 봇 디렉토리 → /bot (읽기 전용)
            volumes={
                bot_dir: {"bind": "/bot", "mode": "ro"},
            },

            # 리소스 제한
            nano_cpus=self.config.cpu_quota,
            mem_limit=self.config.mem_limit,
            memswap_limit=self.config.mem_swap_limit,
            pids_limit=self.config.pids_limit,

            # 보안
            cap_drop=self.config.cap_drop,
            read_only=self.config.read_only_rootfs,
            # /tmp은 쓰기 가능해야 Python이 동작
            tmpfs={"/tmp": "size=10m,noexec"},

            # 네트워크
            network=network.name,

            # 기타
            detach=True,
            auto_remove=False,
            stdin_open=False,
            tty=False,
        )

        logger.info(
            "컨테이너 생성: %s (이미지: %s)",
            self.container_name, self.config.base_image,
        )

    def _start_container(self) -> None:
        """컨테이너를 시작한다."""
        assert self._container is not None
        self._container.start()
        logger.info("컨테이너 시작: %s", self.container_name)

    # ──────────────────────────────────────────────
    #  내부 — 헬스체크
    # ──────────────────────────────────────────────

    def _wait_for_healthy(self) -> None:
        """
        컨테이너의 HTTP 서버가 응답할 때까지 폴링한다.
        타임아웃 초과 시 RuntimeError.
        """
        assert self._container is not None

        # 컨테이너 네트워크 IP 획득
        self._container.reload()
        networks = self._container.attrs["NetworkSettings"]["Networks"]
        net_info = networks.get(self.config.network_name)
        if net_info is None:
            # 네트워크 이름으로 못 찾으면 첫 번째 네트워크 사용
            net_info = next(iter(networks.values()))
        self._container_ip = net_info["IPAddress"]

        if not self._container_ip:
            raise RuntimeError(
                f"컨테이너 {self.container_name}의 IP를 획득할 수 없습니다."
            )

        logger.info(
            "컨테이너 IP 할당: %s → %s",
            self.container_name, self._container_ip,
        )

        # HTTP 헬스체크 폴링
        import urllib.request
        import urllib.error

        health_url = self.health_url
        assert health_url is not None

        deadline = time.monotonic() + self.config.container_startup_timeout
        last_error = None

        while time.monotonic() < deadline:
            try:
                req = urllib.request.Request(health_url, method="GET")
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        logger.info("컨테이너 정상 기동: %s", self.container_name)
                        return
            except Exception as e:
                last_error = e

            time.sleep(self.config.container_health_interval)

        raise RuntimeError(
            f"컨테이너 {self.container_name} 헬스체크 타임아웃 "
            f"({self.config.container_startup_timeout}초). "
            f"마지막 오류: {last_error}"
        )
