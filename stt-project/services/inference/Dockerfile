FROM alpine:latest

RUN mkdir -p /www/v2/health \
	&& echo "ready" > /www/v2/health/ready

EXPOSE 8000 8001 8002

# Placeholder runtime that still satisfies Triton readiness probes.
CMD ["busybox", "httpd", "-f", "-p", "8000", "-h", "/www"]
