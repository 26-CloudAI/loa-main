FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" redis firebase-admin psycopg2-binary google-cloud-storage "numpy>=2.0"

# arena_core (도메인 무관 엔진/타입) — 모든 게임이 의존
COPY core/ ./core/

# battle_royale → src/arena/ (gcs_weights는 src/arena 하위에 포함됨)
COPY battle_royale/src/ ./src/
# mock_stocks → src/stocks/ (같은 src/ 패키지 아래에 병합)
COPY mock_stocks/src/stocks/ ./src/stocks/

# 양쪽 봇을 하나의 bots/ 패키지로 병합 (파일명 충돌 없음)
COPY battle_royale/bots/ ./bots/
COPY mock_stocks/bots/ ./bots/

# 통합 엔트리포인트
COPY run_server.py ./

EXPOSE 8080

CMD ["sh", "-c", "python run_server.py --host 0.0.0.0 --port ${PORT:-8080}"]
