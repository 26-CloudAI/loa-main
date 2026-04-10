"""
AI Arena — 인증 모듈

비밀번호 해싱과 JWT 토큰을 표준 라이브러리만으로 구현.
외부 의존성 없이 동작하며, 프로덕션에서는 bcrypt/PyJWT로 교체 권장.

보안 설계:
  - 비밀번호: PBKDF2-HMAC-SHA256 (iterations=260,000)
    OWASP 2023 권장 최소 600,000이지만, 개발 단계에서는 260,000 사용.
    프로덕션에서는 hashlib.pbkdf2_hmac의 iterations를 올리거나 bcrypt로 교체.
  - 토큰: HMAC-SHA256 서명 JWT (HS256)
    표준 라이브러리만으로 구현한 최소 JWT.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Optional


# ──────────────────────────────────────────────
#  비밀번호 해싱
# ──────────────────────────────────────────────

# OWASP 권장 기반 반복 횟수 (pbkdf2_hmac sha256)
_PBKDF2_ITERATIONS = 260_000
_SALT_BYTES = 32
_HASH_BYTES = 32


def generate_salt() -> str:
    """암호학적으로 안전한 솔트 생성. hex 문자열로 반환."""
    return secrets.token_hex(_SALT_BYTES)


def hash_password(password: str, salt: str) -> str:
    """비밀번호를 해싱. hex 문자열로 반환."""
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        _PBKDF2_ITERATIONS,
        dklen=_HASH_BYTES,
    )
    return dk.hex()


def verify_password(password: str, salt: str, password_hash: str) -> bool:
    """비밀번호 검증. 타이밍 공격 방지를 위해 hmac.compare_digest 사용."""
    computed = hash_password(password, salt)
    return hmac.compare_digest(computed, password_hash)


# ──────────────────────────────────────────────
#  JWT 토큰 (HS256, 표준 라이브러리 구현)
# ──────────────────────────────────────────────

@dataclass(frozen=True)
class TokenConfig:
    secret_key: str = ""                # 비어있으면 자동 생성
    algorithm: str = "HS256"
    access_token_expire_sec: int = 3600     # 1시간
    refresh_token_expire_sec: int = 604800  # 7일

    def __post_init__(self):
        if not self.secret_key:
            # 서버 시작 시 랜덤 시크릿 생성
            object.__setattr__(self, "secret_key", secrets.token_hex(32))


def _b64url_encode(data: bytes) -> str:
    """URL-safe base64 인코딩 (패딩 제거)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """URL-safe base64 디코딩 (패딩 복원)."""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_token(
    payload: dict,
    config: TokenConfig,
    expires_in: Optional[int] = None,
) -> str:
    """JWT 토큰 생성."""
    header = {"alg": config.algorithm, "typ": "JWT"}

    now = int(time.time())
    exp = expires_in or config.access_token_expire_sec
    payload = {
        **payload,
        "iat": now,
        "exp": now + exp,
    }

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())

    signing_input = f"{header_b64}.{payload_b64}"
    signature = hmac.new(
        config.secret_key.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature_b64 = _b64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


def decode_token(token: str, config: TokenConfig) -> Optional[dict]:
    """
    JWT 토큰을 검증하고 페이로드를 반환.
    서명 불일치, 만료, 형식 오류 시 None 반환.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None

    header_b64, payload_b64, signature_b64 = parts

    # 서명 검증
    signing_input = f"{header_b64}.{payload_b64}"
    expected_sig = hmac.new(
        config.secret_key.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    try:
        actual_sig = _b64url_decode(signature_b64)
    except Exception:
        return None

    if not hmac.compare_digest(expected_sig, actual_sig):
        return None

    # 페이로드 파싱
    try:
        payload_bytes = _b64url_decode(payload_b64)
        payload = json.loads(payload_bytes)
    except (json.JSONDecodeError, Exception):
        return None

    # 만료 확인
    exp = payload.get("exp")
    if exp is not None and int(time.time()) > exp:
        return None

    return payload


# ──────────────────────────────────────────────
#  인증 서비스
# ──────────────────────────────────────────────

class AuthService:
    """
    유저 등록, 로그인, 토큰 발급/검증을 담당.
    DB 리포지토리와 조합하여 사용.
    """

    def __init__(self, user_repo, token_config: TokenConfig = TokenConfig()):
        from ..db.user_repo import UserRepository
        self.users: UserRepository = user_repo
        self.token_config = token_config

    def register(
        self,
        username: str,
        password: str,
        display_name: Optional[str] = None,
    ) -> tuple[bool, str, Optional[dict]]:
        """
        유저 등록.
        반환: (성공 여부, 메시지, 유저 정보 dict 또는 None)
        """
        # 입력 검증
        if len(username) < 3 or len(username) > 20:
            return False, "아이디는 3~20자여야 합니다.", None
        if not username.isalnum() and "_" not in username:
            return False, "아이디는 영문, 숫자, 밑줄(_)만 허용됩니다.", None
        if len(password) < 6:
            return False, "비밀번호는 최소 6자여야 합니다.", None

        if self.users.username_exists(username):
            return False, "이미 사용 중인 아이디입니다.", None

        salt = generate_salt()
        pw_hash = hash_password(password, salt)
        display = display_name or username

        user = self.users.create(username, display, pw_hash, salt)

        return True, "등록 완료", {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
        }

    def login(
        self, username: str, password: str
    ) -> tuple[bool, str, Optional[dict]]:
        """
        로그인.
        반환: (성공 여부, 메시지, {access_token, user} 또는 None)
        """
        user = self.users.get_by_username(username)
        if user is None:
            return False, "존재하지 않는 아이디입니다.", None

        if not user.is_active:
            return False, "비활성화된 계정입니다.", None

        if not verify_password(password, user.salt, user.password_hash):
            return False, "비밀번호가 일치하지 않습니다.", None

        self.users.update_last_login(user.id)

        token = create_token(
            {"user_id": user.id, "username": user.username},
            self.token_config,
        )

        return True, "로그인 성공", {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
            },
        }

    def authenticate_token(self, token: str) -> Optional[dict]:
        """
        토큰을 검증하고 페이로드를 반환.
        유효하지 않으면 None.
        """
        return decode_token(token, self.token_config)
