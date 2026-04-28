# Docker Compose (Development)

Use Docker for all local runs (frontend + backend + gateway + infra dependencies).

## Start
```bash
just up
```

## Stop
```bash
just down
```

## Hot Reload
- Dashboard: Next.js dev server runs with bind mount (`apps/dashboard:/app`).
- Backend API: `uvicorn --reload` runs with bind mount (`backend:/app`).
- Worker: `watchfiles` restarts `rq worker` on Python file changes.
- Gateway: `watchfiles` restarts Neonize bridge on Python file changes.

## Repo-Local Data Mounts
All Docker runtime and persistence mounts live under the repo-local `data/`
directory via bind mounts. This includes `node_modules`, Python virtualenvs,
gateway session state, PostgreSQL data, and MinIO data.

Existing named Docker volumes are not migrated automatically. After pulling
this change, old dev volumes remain in Docker but are no longer mounted by
the dev stack.

## WhatsApp Session Persistence (Gateway)
The gateway stores Neonize session state in the repo-local path `data/gateway/session`
mounted at `/data`.
`NEONIZE_DATABASE_PATH` defaults to `/data/neonize.db`, so login/session state survives container restarts.

Reset session state intentionally:

```bash
just reset-whatsapp-session
```

## Smoke Gates

Run Docker smoke checks (services + migrations):

```bash
just smoke-docker
```

Run backup/restore DR baseline smoke:

```bash
just smoke-dr-restore
```

Run both:

```bash
just smoke-all
```

Scripts:
- `infra/compose/smoke/docker-smoke.sh`
- `infra/compose/smoke/dr-backup-restore.sh`

Restore runbook:
- `infra/compose/DR_RUNBOOK.md`
