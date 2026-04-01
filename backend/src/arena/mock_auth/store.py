"""
AI Arena — Mock 사용자 스토어

db_design.md의 users 테이블 목표 스키마를 흉내 낸다.
나중에 Firebase Auth 전환 시 이 모듈만 교체하면 된다.

사용자 응답 필드는 DB 설계의 users 테이블과 동일하게 유지한다:
  id, firebase_uid, email, email_verified, username,
  display_name, photo_url, auth_provider, role,
  created_at, updated_at, last_login_at, is_active,
  banned_reason, banned_at
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Optional


# ──────────────────────────────────────────────
#  Mock 사용자 모델 (users 테이블 목표 스키마 반영)
# ──────────────────────────────────────────────

@dataclass
class MockUser:
    id: int
    firebase_uid: str           # Mock에서는 "mock_<username>" 형태
    email: str
    email_verified: bool
    username: str
    display_name: str
    photo_url: Optional[str]
    auth_provider: str          # password | google.com | github.com
    role: str                   # user | admin
    created_at: str
    updated_at: str
    last_login_at: Optional[str]
    is_active: bool
    banned_reason: Optional[str]
    banned_at: Optional[str]
    # Mock 전용: 실제 비밀번호 저장 (운영에서는 Firebase가 담당)
    _password: str = field(repr=False, default="")

    def to_profile(self) -> dict:
        """프론트엔드로 내려주는 사용자 프로필. _password 제외."""
        return {
            "id": self.id,
            "firebase_uid": self.firebase_uid,
            "email": self.email,
            "email_verified": self.email_verified,
            "username": self.username,
            "display_name": self.display_name,
            "photo_url": self.photo_url,
            "auth_provider": self.auth_provider,
            "role": self.role,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_login_at": self.last_login_at,
            "is_active": self.is_active,
            "banned_reason": self.banned_reason,
            "banned_at": self.banned_at,
        }


# ──────────────────────────────────────────────
#  Mock 토큰 유틸 (JWT 흉내, 표준 라이브러리만 사용)
# ──────────────────────────────────────────────

_MOCK_SECRET = "mock-secret-not-for-production"
_TOKEN_TTL = 3600  # 1시간 (Firebase ID Token 기본 TTL과 동일)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * padding)


def issue_mock_token(firebase_uid: str) -> str:
    """
    Mock Access Token 발급.
    형식: base64(header).base64(payload).base64(signature)
    Firebase ID Token 구조를 흉내 내어 나중에 교체하기 쉽게 한다.
    """
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url_encode(json.dumps({
        "sub": firebase_uid,        # Firebase의 uid 클레임과 동일 키 사용
        "iat": int(time.time()),
        "exp": int(time.time()) + _TOKEN_TTL,
    }).encode())

    sig_input = f"{header}.{payload}".encode()
    sig = hmac.new(_MOCK_SECRET.encode(), sig_input, hashlib.sha256).digest()
    signature = _b64url_encode(sig)

    return f"{header}.{payload}.{signature}"


def verify_mock_token(token: str) -> Optional[str]:
    """
    Mock Token 검증. 유효하면 firebase_uid 반환, 실패하면 None.
    Firebase Admin SDK의 verify_id_token() 인터페이스와 동일하게 동작한다.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, sig_b64 = parts

        # 서명 검증
        sig_input = f"{header_b64}.{payload_b64}".encode()
        expected_sig = hmac.new(_MOCK_SECRET.encode(), sig_input, hashlib.sha256).digest()
        expected_b64 = _b64url_encode(expected_sig)
        if not hmac.compare_digest(sig_b64, expected_b64):
            return None

        # 만료 검증
        payload = json.loads(_b64url_decode(payload_b64))
        if payload.get("exp", 0) < int(time.time()):
            return None

        return payload.get("sub")

    except Exception:
        return None


# ──────────────────────────────────────────────
#  Mock 사용자 데이터 (하드코딩)
# ──────────────────────────────────────────────

_MOCK_USERS: list[MockUser] = [
    MockUser(
        id=1,
        firebase_uid="mock_alice",
        email="alice@arena.dev",
        email_verified=True,
        username="alice",
        display_name="Alice",
        photo_url=None,
        auth_provider="password",
        role="admin",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        last_login_at=None,
        is_active=True,
        banned_reason=None,
        banned_at=None,
        _password="alice1234",
    ),
    MockUser(
        id=2,
        firebase_uid="mock_bob",
        email="bob@arena.dev",
        email_verified=True,
        username="bob",
        display_name="Bob",
        photo_url=None,
        auth_provider="password",
        role="user",
        created_at="2026-01-02T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
        last_login_at=None,
        is_active=True,
        banned_reason=None,
        banned_at=None,
        _password="bob1234",
    ),
    MockUser(
        id=3,
        firebase_uid="mock_carol",
        email="carol@arena.dev",
        email_verified=False,
        username="carol",
        display_name="Carol",
        photo_url=None,
        auth_provider="google.com",
        role="user",
        created_at="2026-01-03T00:00:00Z",
        updated_at="2026-01-03T00:00:00Z",
        last_login_at=None,
        is_active=True,
        banned_reason=None,
        banned_at=None,
        _password="carol1234",
    ),
    MockUser(
        id=4,
        firebase_uid="mock_banned",
        email="banned@arena.dev",
        email_verified=True,
        username="banned_user",
        display_name="Banned User",
        photo_url=None,
        auth_provider="password",
        role="user",
        created_at="2026-01-04T00:00:00Z",
        updated_at="2026-01-04T00:00:00Z",
        last_login_at=None,
        is_active=False,
        banned_reason="운영 정책 위반",
        banned_at="2026-02-01T00:00:00Z",
        _password="banned1234",
    ),
]

# 빠른 조회를 위한 인덱스
_by_email: dict[str, MockUser] = {u.email: u for u in _MOCK_USERS}
_by_firebase_uid: dict[str, MockUser] = {u.firebase_uid: u for u in _MOCK_USERS}
_by_id: dict[int, MockUser] = {u.id: u for u in _MOCK_USERS}


# ──────────────────────────────────────────────
#  공개 인터페이스
# ──────────────────────────────────────────────

def get_user_by_email(email: str) -> Optional[MockUser]:
    return _by_email.get(email)


def get_user_by_firebase_uid(uid: str) -> Optional[MockUser]:
    return _by_firebase_uid.get(uid)


def get_user_by_id(user_id: int) -> Optional[MockUser]:
    return _by_id.get(user_id)


def verify_password(user: MockUser, password: str) -> bool:
    """Mock 비밀번호 검증. 운영에서는 Firebase가 담당하므로 이 함수는 사라진다."""
    return user._password == password


def update_last_login(user: MockUser) -> None:
    """last_login_at 갱신. 운영에서는 DB Upsert에서 처리된다."""
    from datetime import datetime, timezone
    user.last_login_at = datetime.now(timezone.utc).isoformat()
    user.updated_at = user.last_login_at
