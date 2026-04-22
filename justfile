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
    rm -rf data/gateway/session

smoke-docker:
    bash infra/compose/smoke/docker-smoke.sh

smoke-dr-restore:
    bash infra/compose/smoke/dr-backup-restore.sh

smoke-all:
    just smoke-docker
    just smoke-dr-restore
