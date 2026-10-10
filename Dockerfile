FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY web ./web

# Render injects PORT; default 8000 for local docker runs
EXPOSE 8000
CMD ["sh", "-c", "uvicorn api.chat.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
