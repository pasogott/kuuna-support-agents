set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

compose_file := "infra/compose/docker-compose.dev.yml"

default:
    @just --list

up:
    docker compose -f {{compose_file}} up --build

down:
    docker compose -f {{compose_file}} down

restart service:
    docker compose -f {{compose_file}} restart {{service}}

logs:
    docker compose -f {{compose_file}} logs -f

logs-service service:
    docker compose -f {{compose_file}} logs -f {{service}}

ps:
    docker compose -f {{compose_file}} ps

migrate:
    docker compose -f {{compose_file}} exec backend uv run alembic upgrade head

shell-backend:
    docker compose -f {{compose_file}} exec backend sh

shell-worker:
    docker compose -f {{compose_file}} exec worker sh

shell-gateway:
    docker compose -f {{compose_file}} exec gateway sh

shell-dashboard:
    docker compose -f {{compose_file}} exec dashboard sh

reset-whatsapp-session:
    docker compose -f {{compose_file}} stop gateway
    rm -rf data/gateway/session

smoke-docker:
    bash infra/compose/smoke/docker-smoke.sh

smoke-dr-restore:
    bash infra/compose/smoke/dr-backup-restore.sh

smoke-all:
    just smoke-docker
    just smoke-dr-restore

# Client-facing daily report (git-backed time estimate; optional gh metadata)
daily-report date="" tz="+01:00" gap="120" hours="0":
    # Usage:
    #   just daily-report                       # today (in tz), gap=120m
    #   just daily-report date=2026-04-23       # explicit day
    #   just daily-report date=2026-04-23 gap=90 tz=+01:00
    if [ -n "{{date}}" ]; then \
      if [ "{{hours}}" != "0" ] && [ -n "{{hours}}" ]; then \
        python3 scripts/kuuna_daily_report.py --repo "$(pwd)" --date "{{date}}" --tz-offset "{{tz}}" --gap-minutes "{{gap}}" --engineering-hours "{{hours}}"; \
      else \
        python3 scripts/kuuna_daily_report.py --repo "$(pwd)" --date "{{date}}" --tz-offset "{{tz}}" --gap-minutes "{{gap}}"; \
      fi; \
    else \
      if [ "{{hours}}" != "0" ] && [ -n "{{hours}}" ]; then \
        python3 scripts/kuuna_daily_report.py --repo "$(pwd)" --tz-offset "{{tz}}" --gap-minutes "{{gap}}" --engineering-hours "{{hours}}"; \
      else \
        python3 scripts/kuuna_daily_report.py --repo "$(pwd)" --tz-offset "{{tz}}" --gap-minutes "{{gap}}"; \
      fi; \
    fi
