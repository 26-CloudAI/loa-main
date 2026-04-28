import json
import os

import firebase_admin
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth, credentials

# 파이어베이스 초기화 (한 번만 실행)
_creds_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
if _creds_json:
    # GCP Cloud Run: Secret Manager에서 JSON 문자열로 주입
    cred = credentials.Certificate(json.loads(_creds_json))
else:
    # 로컬: 파일 경로 사용
    _creds_path = os.environ.get(
        "FIREBASE_CREDENTIALS_PATH",
        "src/arena/server/secrets/serviceAccountKey.json",
    )
    cred = credentials.Certificate(_creds_path)

firebase_admin.initialize_app(cred)

security = HTTPBearer()

async def verify_firebase_token(res: HTTPAuthorizationCredentials = Depends(security)):
    """프론트엔드에서 보낸 Firebase ID 토큰을 검증합니다."""
    token = res.credentials
    try:
        # 토큰 검증 및 디코딩
        decoded_token = auth.verify_id_token(token)
        return decoded_token  # 유저 정보 반환 (uid, email 등 포함)
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=f"유효하지 않은 인증 토큰입니다: {str(e)}"
        )