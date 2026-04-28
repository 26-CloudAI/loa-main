"""
AI Arena — Mock Auth 스키마

요청/응답 데이터 구조.
Firebase Auth 전환 후에도 API 응답 형태가 변하지 않도록
최종 구조를 기준으로 정의한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class LoginRequest:
    """
    POST /auth/login 요청 바디.
    Mock: email + password
    Firebase 전환 후: Firebase ID Token만 전달하는 구조로 교체
    """
    email: str
    password: str


@dataclass
class LoginResponse:
    """
    POST /auth/login 응답.
    access_token은 Mock Token (나중에 Firebase ID Token으로 교체).
    user는 users 테이블 목표 스키마 그대로.
    """
    access_token: str
    token_type: str              # 항상 "bearer"
    expires_in: int              # 초 단위 (Firebase 기본값과 동일: 3600)
    user: dict                   # MockUser.to_profile() 결과


@dataclass
class MeResponse:
    """GET /auth/me 응답 — 현재 로그인 사용자 프로필."""
    user: dict
