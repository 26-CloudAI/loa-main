FROM python:3.11-slim

RUN groupadd -r bot-runner && useradd -r -g bot-runner -u 10001 bot-runner

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py schemas.py cache.py executor.py policy.py serve.py ./

RUN chown -R bot-runner:bot-runner /app

USER 10001

EXPOSE 8001
# 프로그래매틱 런처로 기동(serve.py). `uvicorn main:app` CLI 는 gVisor 에서 /run 당
# ~150ms 추가 오버헤드가 있어 lock-step BR2 게임을 느리게 만들었다. 자세한 이유는 serve.py.
CMD ["python", "serve.py"]
