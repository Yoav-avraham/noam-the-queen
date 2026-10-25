FROM synchronizer-deps:latest

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	PYTHONPATH=/app/src

WORKDIR /app

COPY services/synchronizer /app

CMD ["python", "-m", "synchronizer"]
