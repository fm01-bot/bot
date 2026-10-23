FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /bot

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY assets/fonts /usr/share/fonts/truetype/open-sans/

COPY . .
RUN uv sync --frozen --no-dev

CMD ["uv", "run", "--no-dev", "main.py"]
