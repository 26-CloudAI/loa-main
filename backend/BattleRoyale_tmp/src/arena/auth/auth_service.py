"""
AI Arena — 인증 모듈

JWT 토큰은 mock_auth(로컬 개발용)에서 사용.
프로덕션 인증은 Firebase Authentication으로 처리.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Optional


# ──────────────────────────────────────────────
#  JWT 토큰 (HS256, 표준 라이브러리 구현)
#  mock_auth 로컬 개발 환경에서 사용
# ──────────────────────────────────────────────

@dataclass(frozen=True)
class TokenConfig:
    secret_key: str = ""
    algorithm: str = "HS256"
    access_token_expire_sec: int = 3600     # 1시간
    refresh_token_expire_sec: int = 604800  # 7일

    def __post_init__(self):
        if not self.secret_key:
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

    try:
        payload_bytes = _b64url_decode(payload_b64)
        payload = json.loads(payload_bytes)
    except (json.JSONDecodeError, Exception):
        return None

    exp = payload.get("exp")
    if exp is not None and int(time.time()) > exp:
        return None

    return payload


# ──────────────────────────────────────────────
#  Firebase 유저 서비스
# ──────────────────────────────────────────────

class FirebaseUserService:
    """
    Firebase 토큰으로 DB 유저를 조회하거나 신규 생성.
    firebase_handler.py의 verify_firebase_token()이 반환한
    decoded_token dict를 받아 처리한다.
    """

    def __init__(self, user_repo):
        from ..db.user_repo import UserRepository
        self.users: UserRepository = user_repo

    def get_or_create_user(self, decoded_token: dict):
        """
        Firebase 디코딩된 토큰으로 DB 유저를 조회하거나 생성한다.
        반환: User
        """
        firebase_uid = decoded_token.get("uid") or decoded_token.get("user_id", "")
        user = self.users.get_by_firebase_uid(firebase_uid)

        if user:
            self.users.update_last_login(user.id)
            return self.users.get_by_id(user.id)

        email = decoded_token.get("email", "")
        display_name = (
            decoded_token.get("name")
            or (email.split("@")[0] if email else None)
            or firebase_uid[:12]
        )
        auth_provider = (
            decoded_token.get("firebase", {}).get("sign_in_provider", "firebase")
        )
        photo_url = decoded_token.get("picture")
        username = self._generate_username(email, firebase_uid)

        return self.users.create(
            firebase_uid, username, display_name, email, auth_provider, photo_url
        )

    def _generate_username(self, email: str, firebase_uid: str) -> str:
        """이메일 앞부분 또는 firebase_uid로 유저명 자동 생성."""
        if email:
            base = re.sub(r"[^a-zA-Z0-9_]", "_", email.split("@")[0])[:20]
            if len(base) >= 3:
                return base
        return firebase_uid[:16]
