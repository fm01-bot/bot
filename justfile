set windows-shell := ["powershell", "-NoLogo", "-Command"]
set quiet
set dotenv-load := true

default:
  just --list

migrate:
  docker compose run --rm bot uv run alembic upgrade head

format:
  uv run ruff format .

lint:
  uv run ruff check --fix .

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

# Restarts only the bot; the gateway proxy keeps the shards connected. Services are listed so the proxy is never touched.
deploy:
  git fetch --all
  git reset --hard origin/main
  uv sync
  just up db
  just migrate
  docker compose build bot
  just up --remove-orphans db lavalink redis bot

# Recreates the gateway proxy, which reconnects every shard to Discord. Only for proxy upgrades and SHARD_COUNT changes.
deploy-proxy:
  docker compose --profile gateway-proxy pull gateway-proxy
  docker compose --profile gateway-proxy up -d --force-recreate gateway-proxy
  just up bot

[windows]
debug:
  if (docker compose ps bot --status running -q 2>$null) { \
    just restart bot; \
  } else { \
    uv sync; \
    just up db; \
    just migrate; \
    just up; \
  }
  just logs -f bot

[unix]
debug:
  if [ -n "$(docker compose ps bot --status running -q 2>/dev/null)" ]; then \
    just restart bot; \
  else \
    uv sync; \
    just up db; \
    just migrate; \
    just up; \
  fi
  just logs -f bot

destroy *ARGS:
  docker compose down -v {{ARGS}}
