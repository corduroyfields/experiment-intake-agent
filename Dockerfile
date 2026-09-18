# Container recipe Cloud Run builds from. Installs exact versions from uv.lock, then starts main.py.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
# main.py listens on $PORT, which Cloud Run sets (8080 by default).
CMD [".venv/bin/python", "main.py"]
