FROM rest-api-deps:latest

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
	PYTHONPATH=/app/src

WORKDIR /app

COPY services/rest-api /app

EXPOSE 8080

CMD ["/app/entrypoint.sh"]
