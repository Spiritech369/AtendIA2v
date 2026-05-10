# ── Backend — desarrollo con hot-reload ─────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Instalar uv (gestor de paquetes ultra-rápido)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Instalar dependencias primero (cacheable si pyproject no cambia)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copiar el código fuente (será sobreescrito por el volumen en dev)
COPY . .

EXPOSE 8001

# Correr migraciones y levantar con hot-reload
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn atendia.main:app --host 0.0.0.0 --port 8001 --reload"]
