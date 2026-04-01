"""
AI Arena — Mock Auth 라우터

엔드포인트:
  POST /auth/login          이메일 + 비밀번호로 로그인, Mock Token 발급
  POST /auth/logout         클라이언트 토큰 폐기 안내 (서버 상태 없음)
  GET  /auth/me             현재 로그인 사용자 프로필 조회
  GET  /auth/users          Mock 사용자 목록 조회 (개발 편의용)

Firebase 전환 시 교체 포인트:
  - login: Firebase ID Token 검증 + DB Upsert로 교체
  - verify_token 의존성: Firebase Admin SDK verify_id_token()으로 교체
  - /auth/users: 삭제
"""

from __future__ import annotations

from typing import Optional

try:
    from fastapi import APIRouter, Depends, HTTPException
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
except ImportError as e:
    raise ImportError("fastapi가 필요합니다: pip install fastapi") from e

from .store import (
    get_user_by_email,
    get_user_by_firebase_uid,
    verify_password,
    verify_mock_token,
    issue_mock_token,
    update_last_login,
    _MOCK_USERS,
    MockUser,
)

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


# ──────────────────────────────────────────────
#  공용 의존성: 토큰 → 사용자
# ──────────────────────────────────────────────

def _get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> MockUser:
    """
    Authorization: Bearer <token> 헤더를 검증하고 현재 사용자를 반환.

    Firebase 전환 시 이 함수 내부만 교체하면 된다:
        firebase_uid = firebase_admin.auth.verify_id_token(token)["uid"]
        user = db.query(users).filter_by(firebase_uid=firebase_uid).first()
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="인증 토큰이 없습니다.")

    firebase_uid = verify_mock_token(credentials.credentials)
    if firebase_uid is None:
        raise HTTPException(status_code=401, detail="유효하지 않거나 만료된 토큰입니다.")

    user = get_user_by_firebase_uid(firebase_uid)
    if user is None:
        raise HTTPException(status_code=401, detail="사용자를 찾을 수 없습니다.")

    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail={
                "message": "계정이 정지되었습니다.",
                "banned_reason": user.banned_reason,
                "banned_at": user.banned_at,
            },
        )

    return user


# ──────────────────────────────────────────────
#  엔드포인트
# ──────────────────────────────────────────────

@router.post("/login")
def login(body: dict):
    """
    이메일 + 비밀번호로 로그인하고 Mock Token을 발급한다.

    요청:
        { "email": "alice@arena.dev", "password": "alice1234" }

    응답:
        {
            "access_token": "<mock_token>",
            "token_type": "bearer",
            "expires_in": 3600,
            "user": { ...users 스키마... }
        }

    Firebase 전환 후:
        - 프론트가 Firebase SDK로 로그인하고 ID Token을 이 엔드포인트로 전달
        - 서버는 Firebase Admin SDK로 토큰 검증 후 DB Upsert
    """
    email = body.get("email", "").strip()
    password = body.get("password", "")

    if not email or not password:
        raise HTTPException(status_code=400, detail="email과 password는 필수입니다.")

    user = get_user_by_email(email)
    if user is None or not verify_password(user, password):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")

    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail={
                "message": "계정이 정지되었습니다.",
                "banned_reason": user.banned_reason,
                "banned_at": user.banned_at,
            },
        )

    update_last_login(user)
    token = issue_mock_token(user.firebase_uid)

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 3600,
        "user": user.to_profile(),
    }


@router.post("/logout")
def logout(_: MockUser = Depends(_get_current_user)):
    """
    로그아웃.
    Mock에서는 서버 상태가 없으므로 클라이언트에서 토큰을 삭제하면 된다.
    Firebase 전환 후에도 서버 측 처리는 동일(Firebase 토큰 취소는 선택적).
    """
    return {"message": "로그아웃되었습니다. 클라이언트에서 토큰을 삭제하세요."}


@router.get("/me")
def get_me(current_user: MockUser = Depends(_get_current_user)):
    """
    현재 로그인 사용자 프로필 조회.

    응답: users 테이블 목표 스키마 그대로
    """
    return {"user": current_user.to_profile()}


@router.get("/users")
def list_mock_users():
    """
    Mock 사용자 목록 (개발 편의용).
    비밀번호와 테스트 계정 정보를 확인하기 위한 엔드포인트.

    Firebase 전환 후 이 엔드포인트는 삭제한다.
    """
    return {
        "notice": "이 엔드포인트는 개발용 Mock입니다. 프로덕션에서 제거하세요.",
        "users": [
            {
                **u.to_profile(),
                "_mock_password": u._password,  # 개발 편의: 비밀번호 노출
            }
            for u in _MOCK_USERS
        ],
    }
