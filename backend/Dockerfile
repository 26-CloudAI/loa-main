FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" redis firebase-admin psycopg2-binary google-cloud-storage "numpy>=2.0"

# --- C2 헤드리스 Godot 러너 런타임 (서버사이드 시뮬). 기본 비활성 — BR2_RUNNER_ENABLED=1 로 켜야 동작. ---
# linux_server 빌드는 더미 비디오/오디오 드라이버라 디스플레이/GPU 없이 헤드리스 실행.
# game.pck 는 아래 COPY BattleRoyale2/ 로 /app/BattleRoyale2/runner/game.pck 에 포함됨.
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget ca-certificates unzip libfontconfig1 libfreetype6 \
    && wget -q https://github.com/godotengine/godot-builds/releases/download/3.6-stable/Godot_v3.6-stable_linux_server.64.zip \
    && unzip -q Godot_v3.6-stable_linux_server.64.zip \
    && mv Godot_v3.6-stable_linux_server.64 /usr/local/bin/godot_server \
    && chmod +x /usr/local/bin/godot_server \
    && rm -f Godot_v3.6-stable_linux_server.64.zip \
    && apt-get purge -y wget unzip && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# arena_core (도메인 무관 엔진/타입) — 모든 게임이 의존
COPY core/ ./core/

# battle_royale → src/arena/ (gcs_weights는 src/arena 하위에 포함됨)
COPY battle_royale/src/ ./src/
# mock_stocks → src/stocks/ (같은 src/ 패키지 아래에 병합)
COPY mock_stocks/src/stocks/ ./src/stocks/

# 양쪽 봇을 하나의 bots/ 패키지로 병합 (파일명 충돌 없음)
COPY battle_royale/bots/ ./bots/
COPY mock_stocks/bots/ ./bots/

# 새 Godot 게임(BattleRoyale2) — self-contained 패키지 (자체 src/arena, bots 포함)
# /app/BattleRoyale2 로 통째 복사 → run_server 가 /battleroyale2 에 mount
COPY BattleRoyale2/ ./BattleRoyale2/

# 통합 엔트리포인트
COPY run_server.py ./

EXPOSE 8080

CMD ["sh", "-c", "python run_server.py --host 0.0.0.0 --port ${PORT:-8080}"]
