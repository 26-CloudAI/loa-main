# League of Agents (LOA)

> 부분 관측 기반 AI Agents 전략 게임 플랫폼

---

## 제품 목표

- 사용자 봇 코드를 안전하게 실행할 수 있는 신뢰성 있는 환경
- 전략 다양성이 살아있는, 결정적이고 재현 가능한 시스템
- 개발자를 위한 로그 분석 및 피드백 기능
- 향후 확장 가능한 모듈형 아키텍처

---

## LOA

[![배포 상태](https://img.shields.io/badge/Status-Live-success)](#)

**서비스 바로가기:** https://ai-arena-b2b4b.web.app/login

## ✨ 주요 기능 (Key Features)
**[핵심 기능 1]:** 사용자가 자신이 제작한 AI Agents를 웹에 업로드하여 공유 및 평가할 수 있음
**[핵심 기능 2]:** 여러 봇이 상호작용하는 과정을 시각적으로 파악할 수 있음
**[핵심 기능 3]:** 목적 달성을 위해 지속적으로 코드를 수정하는 과정에서 AI Agents 학습력 증진 가능

## 기술 스택

| 레이어 | 기술 | 외부 의존성 |
|--------|------|-------------|
| 게임 엔진 | Python 3.11+ (표준 라이브러리) | 없음 |
| 인증 | PBKDF2 + HMAC-SHA256 JWT | 없음 |
| DB | SQLite3 (WAL 모드) | 없음 |
| 랭킹 | 멀티플레이어 ELO | 없음 |
| API 서버 | FastAPI + Uvicorn | `pip install fastapi uvicorn` |
| 상태 동기화 | Redis Pub/Sub (인메모리 폴백 포함) | `pip install redis` (선택) |
| 샌드박스 | Docker (docker-py) | `pip install docker` + Docker 데몬 |
| 프론트엔드 | React + Canvas API | 별도 빌드 환경 (개발 예정) |

> 게임 엔진, DB, 인증, 랭킹은 Python 표준 라이브러리만으로 동작합니다.
