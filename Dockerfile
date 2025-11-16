FROM python:3.13
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /uvx /bin/

COPY . /app
WORKDIR /app
RUN pip install -e .

ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
CMD ["uvicorn", "src.user_service.api:app", "--host", "0.0.0.0", "--port", "8000"]

COPY . /app
WORKDIR /app

# Normalize CRLF->LF and ensure the script is executable (Windows-friendly)
RUN sed -i 's/\r$//' scripts/docker-entrypoint.sh && chmod +x scripts/docker-entrypoint.sh
