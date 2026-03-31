"""
AI Arena — 컨테이너 풀 매니저

하나의 게임 세션에 필요한 모든 봇 컨테이너를 일괄 관리한다.
  - 게임 시작 전: 전체 컨테이너 생성 + 네트워크 구성
  - 게임 종료 후: 전체 컨테이너 + 네트워크 정리

Context manager 지원: `with ContainerPool(...) as pool:` 사용 시 자동 정리.
"""

from __future__ import annotations

import logging
from typing import Optional

try:
    import docker
    from docker.errors import APIError, NotFound
    from docker.models.networks import Network

    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False

from ..bot_interface import BotInterface
from .config import DEFAULT_SANDBOX_CONFIG, SandboxConfig
from .container_manager import ContainerManager
from .docker_adapter import DockerBotAdapter

logger = logging.getLogger(__name__)


class ContainerPool:
    """
    게임 한 판에 사용되는 전체 봇 컨테이너를 관리.

    사용법:
        bot_codes = {"bot_01": "def action(state): return 'STAY'", ...}

        with ContainerPool(bot_codes) as pool:
            adapters = pool.get_adapters()
            engine = GameEngine(adapters, ...)
            engine.run_full_game()
    """

    def __init__(
        self,
        bot_codes: dict[str, str],
        config: SandboxConfig = DEFAULT_SANDBOX_CONFIG,
    ):
        if not DOCKER_AVAILABLE:
            raise RuntimeError(
                "docker 패키지가 설치되지 않았습니다. "
                "'pip install docker'를 실행하세요."
            )

        self.config = config
        self.client = docker.from_env()

        self._bot_codes = bot_codes
        self._managers: dict[str, ContainerManager] = {}
        self._adapters: dict[str, DockerBotAdapter] = {}
        self._network: Optional[Network] = None
        self._started = False

    def __enter__(self):
        self.start_all()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_all()
        return False  # 예외 전파

    # ──────────────────────────────────────────────
    #  공개 API
    # ──────────────────────────────────────────────

    def start_all(self) -> None:
        """모든 봇 컨테이너를 일괄 생성·시작한다."""
        if self._started:
            raise RuntimeError("이미 시작된 풀입니다.")

        try:
            self._create_network()
            self._create_containers()
            self._started = True

            logger.info(
                "컨테이너 풀 시작 완료: %d개 봇", len(self._managers)
            )

        except Exception:
            # 부분 실패 시 정리
            logger.error("풀 시작 중 오류 — 전체 정리 시작", exc_info=True)
            self.stop_all()
            raise

    def stop_all(self) -> None:
        """모든 컨테이너를 정지·삭제하고 네트워크를 제거한다."""
        errors: list[str] = []

        # 컨테이너 정리
        for bot_id, manager in self._managers.items():
            try:
                manager.stop_and_remove()
            except Exception as e:
                errors.append(f"{bot_id}: {e}")
                logger.debug("컨테이너 정리 실패: %s", bot_id, exc_info=True)

        self._managers.clear()
        self._adapters.clear()

        # 네트워크 정리
        if self._network is not None:
            try:
                self._network.remove()
                logger.info("네트워크 제거: %s", self.config.network_name)
            except Exception as e:
                errors.append(f"network: {e}")
            self._network = None

        self._started = False

        if errors:
            logger.warning("정리 중 %d개 오류 발생: %s", len(errors), errors)

    def get_adapters(self) -> list[DockerBotAdapter]:
        """엔진에 전달할 BotInterface 어댑터 목록을 반환."""
        if not self._started:
            raise RuntimeError("풀이 아직 시작되지 않았습니다.")
        return list(self._adapters.values())

    def get_adapter(self, bot_id: str) -> Optional[DockerBotAdapter]:
        """특정 봇의 어댑터를 반환."""
        return self._adapters.get(bot_id)

    def get_all_stats(self) -> list[dict]:
        """모든 봇의 통신 통계."""
        return [adapter.get_stats() for adapter in self._adapters.values()]

    # ──────────────────────────────────────────────
    #  내부
    # ──────────────────────────────────────────────

    def _create_network(self) -> None:
        """격리된 Docker 브릿지 네트워크를 생성한다."""
        # 기존 동명 네트워크 정리
        try:
            existing = self.client.networks.get(self.config.network_name)
            logger.info(
                "기존 네트워크 %s 발견 — 삭제 후 재생성",
                self.config.network_name,
            )
            existing.remove()
        except NotFound:
            pass

        self._network = self.client.networks.create(
            name=self.config.network_name,
            driver="bridge",
            # internal=True: 외부 인터넷 접근 차단
            # (호스트 → 컨테이너 접근은 가능)
            internal=True,
            labels={"managed-by": "ai-arena"},
        )
        logger.info("네트워크 생성: %s (internal=True)", self.config.network_name)

    def _create_containers(self) -> None:
        """모든 봇의 컨테이너를 생성·시작한다."""
        assert self._network is not None

        for bot_id, code in self._bot_codes.items():
            manager = ContainerManager(
                bot_id=bot_id,
                bot_code=code,
                config=self.config,
                client=self.client,
            )

            ip = manager.create_and_start(self._network)

            adapter = DockerBotAdapter(
                bot_id=bot_id,
                action_url=f"http://{ip}:{self.config.container_port}/action",
                config=self.config,
            )

            self._managers[bot_id] = manager
            self._adapters[bot_id] = adapter

            logger.info(
                "봇 준비 완료: %s → %s:%d",
                bot_id, ip, self.config.container_port,
            )
