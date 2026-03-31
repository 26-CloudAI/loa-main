"""
AI Arena — 샌드박스 설정
Docker 컨테이너 리소스 제한, 타임아웃, 네트워크 설정.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SandboxConfig:
    # ── 컨테이너 리소스 제한 ──
    cpu_quota: int = 100_000_000        # nano_cpus: 0.1 코어
    mem_limit: str = "50m"              # 메모리 상한
    mem_swap_limit: str = "50m"         # 스왑 포함 상한 (= 스왑 비활성화)
    pids_limit: int = 32                # 프로세스 수 상한 (fork 폭탄 방지)

    # ── 네트워크 ──
    network_name: str = "ai-arena-net"  # Docker 브릿지 네트워크 이름
    container_port: int = 8000          # 컨테이너 내부 HTTP 서버 포트

    # ── 타임아웃 ──
    action_timeout_sec: float = 0.1     # 봇 응답 타임아웃 (100ms)
    container_startup_timeout: float = 5.0   # 컨테이너 기동 대기 최대 시간
    container_health_interval: float = 0.1   # 헬스체크 폴링 간격

    # ── 이미지 ──
    base_image: str = "python:3.12-alpine"
    container_prefix: str = "ai-arena-bot-"

    # ── 보안 ──
    read_only_rootfs: bool = True       # 루트 파일시스템 읽기 전용
    cap_drop: list[str] | None = None   # 제거할 Linux capabilities

    def __post_init__(self):
        # frozen이라 직접 할당 불가 → object.__setattr__ 사용
        if self.cap_drop is None:
            object.__setattr__(self, "cap_drop", ["ALL"])


DEFAULT_SANDBOX_CONFIG = SandboxConfig()
