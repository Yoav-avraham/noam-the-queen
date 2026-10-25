FROM stream-api-deps:latest

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY common /app/common
COPY services/stream-api /app

CMD ["python", "-m", "stream_api"]
