FROM python:3.12-slim

# uv para instalar dependencias rápido y de forma reproducible.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml README.md ./
COPY server.py auth.py ./

RUN uv pip install --system --no-cache .

# Cloud Run inyecta $PORT en runtime; 8000 es el default para correr local.
ENV PORT=8000
EXPOSE 8000

RUN useradd --create-home appuser
USER appuser

CMD ["python", "server.py"]
