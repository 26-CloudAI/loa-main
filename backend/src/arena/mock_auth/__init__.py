"""
AI Arena — Mock Auth 패키지

Firebase Auth 최종 구조를 흉내 내는 Mock 인증 레이어.
나중에 Firebase Admin SDK 기반 실제 검증으로 교체하기 위해
인터페이스를 최대한 최종 구조와 동일하게 유지한다.

포함 모듈:
  store   — Mock 사용자 데이터 저장소
  schemas — 요청/응답 스키마
  router  — FastAPI 라우터 (/auth/*)
"""
