set windows-shell := ["pwsh", "-NoLogo", "-Command"]
set quiet
set dotenv-load := true

default:
  just --list

sync:
  uv sync

migrate:
  uv run alembic upgrade head

format:
  uv run ruff format

lint:
  uv run ruff check

test *ARGS:
  uv run pytest {{ARGS}}

up *ARGS:
  docker compose up -d {{ARGS}}

down *ARGS:
  docker compose down {{ARGS}}

start *ARGS:
  docker compose start {{ARGS}}

stop *ARGS:
  docker compose stop {{ARGS}}

restart *ARGS:
  docker compose restart {{ARGS}}

logs *ARGS:
  docker compose logs -f {{ARGS}}

deploy:
  git fetch --all
  git reset --hard origin/main
  just sync
  just up db
  just migrate
  docker compose build
  just up -d --remove-orphans

debug:
  just sync
  just up db
  just migrate
  just up

destroy *ARGS:
  docker compose down -v {{ARGS}}
