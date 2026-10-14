FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    libreoffice-writer-nogui \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY . .

RUN uv sync --all-extras

CMD ["sh", "-c", "uv run python tests/fixtures/make_fixtures.py && uv run pytest -m 'not integration' -v"]
