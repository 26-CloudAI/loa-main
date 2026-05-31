FROM python:3.11-slim

RUN groupadd -r bot-runner && useradd -r -g bot-runner -u 10001 bot-runner

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py schemas.py cache.py executor.py policy.py ./

RUN chown -R bot-runner:bot-runner /app

USER 10001

EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
