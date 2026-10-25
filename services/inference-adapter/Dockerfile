FROM inference-adapter-deps:latest

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PYTHON_VERSION=3.12

WORKDIR /app

COPY common /app/common
COPY services/inference-adapter /app

CMD ["python", "-m", "inference_adapter"]
