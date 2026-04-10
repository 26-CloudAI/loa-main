FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" redis firebase-admin psycopg2-binary

COPY src/ ./src/
COPY bots/ ./bots/
COPY run_server.py ./

EXPOSE 8080

CMD ["sh", "-c", "python run_server.py --host 0.0.0.0 --port ${PORT:-8080}"]
