import json
import os
from pathlib import Path

import firebase_admin
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth, credentials

# 파이어베이스 초기화 (한 번만 실행)
_creds_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
if _creds_json:
    # GCP Cloud Run: Secret Manager에서 JSON 문자열로 주입
    cred = credentials.Certificate(json.loads(_creds_json))
    firebase_admin.initialize_app(cred)
else:
    # 로컬: 파일 경로 사용 (없으면 GCP VM의 ADC로 fallback)
    _default_path = Path(__file__).parents[4] / "secrets" / "serviceAccountKey.json"
    _creds_path = os.environ.get("FIREBASE_CREDENTIALS_PATH", str(_default_path))
    if os.path.exists(_creds_path):
        cred = credentials.Certificate(_creds_path)
        firebase_admin.initialize_app(cred)
    else:
        # GCP VM 등에서 ADC(Application Default Credentials)로 초기화.
        # Firebase ID 토큰 검증은 공개 키로 수행되므로 service account key 없이도 작동.
        # FIREBASE_PROJECT_ID 환경변수로 projectId를 명시할 수 있음.
        _project_id = os.environ.get("FIREBASE_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if _project_id:
            firebase_admin.initialize_app(options={"projectId": _project_id})
        else:
            firebase_admin.initialize_app()

security = HTTPBearer()

def verify_firebase_token_value(token: str) -> dict:
    """Firebase ID 토큰 문자열을 검증하고 디코딩된 페이로드를 반환한다.

    clock_skew_seconds=5 : 로컬 Docker 환경에서 컨테이너 클럭이 호스트보다
    최대 수 초 느리게 drift하는 현상(Token used too early)을 허용한다.
    """
    try:
        return auth.verify_id_token(token, clock_skew_seconds=5)
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=f"유효하지 않은 인증 토큰입니다: {str(e)}"
        ) from e


async def verify_firebase_token(res: HTTPAuthorizationCredentials = Depends(security)):
    """프론트엔드에서 보낸 Firebase ID 토큰을 검증합니다."""
    return verify_firebase_token_value(res.credentials)
