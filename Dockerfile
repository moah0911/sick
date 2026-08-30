FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends git curl bubblewrap && rm -rf /var/lib/apt/lists/*
# uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY templates ./templates
RUN uv sync --frozen --no-dev || uv sync --no-dev
COPY . .
RUN chmod +x install.sh
EXPOSE 8000
ENTRYPOINT ["uv", "run", "sick"]
CMD ["--help"]
