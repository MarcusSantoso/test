FROM python:3.13
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /uvx /bin/

# Copy source into image, install, and ensure we don't keep a copy of
# the local `.env` file in the final image. Runtime environment will
# be provided by Docker Compose via `env_file`.
COPY . /app
WORKDIR /app
RUN pip install -e . \
	&& rm -f /app/.env || true

ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
CMD ["uvicorn", "src.user_service.api:app", "--host", "0.0.0.0", "--port", "8000"]

# Normalize CRLF->LF and ensure the script is executable (Windows-friendly)
RUN sed -i 's/\r$//' scripts/docker-entrypoint.sh && chmod +x scripts/docker-entrypoint.sh
