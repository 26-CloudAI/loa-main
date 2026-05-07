FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" redis firebase-admin psycopg2-binary google-cloud-storage "numpy>=2.0"

# GCS 가중치 유틸리티
COPY BattleRoyale/gcs_weights.py ./

# BattleRoyale → src/arena/
COPY BattleRoyale/src/ ./src/
# MockStocks → src/stocks/ (같은 src/ 패키지 아래에 병합)
COPY MockStocks/src/stocks/ ./src/stocks/

# 양쪽 봇을 하나의 bots/ 패키지로 병합 (파일명 충돌 없음)
COPY BattleRoyale/bots/ ./bots/
COPY MockStocks/bots/ ./bots/

# 통합 엔트리포인트
COPY run_server.py ./

EXPOSE 8080

CMD ["sh", "-c", "python run_server.py --host 0.0.0.0 --port ${PORT:-8080}"]
