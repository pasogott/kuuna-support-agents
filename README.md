# Kuuna Support Agents

Staff-operated WhatsApp group agents with sandboxed runtimes, deterministic routing, and dashboard-based governance.

## Status
This repository now contains the **MVP planning docs plus an initial implementation scaffold**.

- PRD: `plan/mvp/PRD.md`
- Project structure plan: `plan/mvp/PROJECT_STRUCTURE_PLAN.md`
- Agent guides: `AGENTS.md`, `apps/dashboard/AGENTS.md`, `backend/AGENTS.md`

Implementation is still targeting a single dev environment first.

## MVP Overview
- One agent instance per WhatsApp group (strict 1:1 active binding)
- WhatsApp group gateway ingestion (messages + media)
- Group-triggered responses (mention/reply/prefix trigger)
- Sandboxed per-group runtime (ephemeral FS; persistence in DB/S3)
- RAG from:
  - group chat history
  - group-specific knowledge
  - common knowledge
- Dashboard for staff to:
  - manage templates, agents, and bindings
  - manage prompts and knowledge (draft/publish/rollback)
  - manage staff users (no self-registration)

## Planned Tech Stack (MVP)
- **Dashboard:** Next.js 15 + TypeScript
- **Control Plane:** FastAPI + Pydantic v2 + SQLAlchemy + Alembic
- **Agent runtime framework:** PydanticAI
- **WhatsApp gateway:** neonize
- **DB:** PostgreSQL 16 + pgvector + RLS
- **Queue:** Redis + RQ
- **Storage:** S3-compatible object storage
- **Observability:** Sentry + structured JSON logs
- **Deployment:** Docker Compose on single host

## Product Principles
- Deterministic routing (`provider_group_id` => exactly one active agent binding)
- Full auditability (append-only audit events)
- Versioned prompts and knowledge with controlled publish/rollback
- Group template as source of truth for tools/model/egress policy
- Strong data traceability via end-to-end trace IDs

## Security and Operations (MVP)
- Staff-only dashboard
- Local login (admin-created users, forced password change on first login)
- Brute-force protections (rate limit + lockout)
- Tool execution with template policy and hard timeouts
- Error monitoring via Sentry
- Ops alerts via WhatsApp operations group

## Sentry Setup (Current)
- Sentry org default is configured in repo root `.sentryclirc`:
  - org: `calumba`
- Service-specific Sentry projects are configured:
  - Backend → `kuuna-backend`
  - Dashboard → `kuuna-dashboard`
  - Gateway → `kuuna-gateway`
- Service-local `.sentryclirc` defaults:
  - `backend/.sentryclirc`
  - `apps/dashboard/.sentryclirc`
  - `services/gateway/.sentryclirc`
- DSNs are pre-wired in dev env templates:
  - `infra/env/backend.env.example` (backend project DSN)
  - `infra/env/dashboard.env.example` (dashboard project DSN)
  - `infra/env/gateway.env.example` (gateway project DSN)
- Backend and gateway send scrubbed events (metadata-only intent).
- Dashboard initializes Sentry for client/server/edge via `@sentry/nextjs`.

## Repository Layout (Scaffold)
- `apps/dashboard` — Next.js 15 + TypeScript dashboard scaffold
- `backend` — FastAPI + domain/worker scaffold (managed with `uv`)
- `services/gateway` — WhatsApp gateway adapter scaffold
- `services/runtime-agent` — base runtime image scaffold
- `packages/api-client-ts` — OpenAPI-generated TS client package scaffold
- `packages/contracts` — shared cross-service contracts scaffold
- `infra` — compose/env/scripts placeholders
- `docs` — architecture/runbooks/ADR placeholders

## Local Setup (Docker-only via Just)
Run everything through the dev stack:

```bash
just up
```

(or via npm wrapper: `npm run dev`)

Services:
- Dashboard: http://localhost:3000
- Backend API: http://localhost:8000
- Worker: background service (RQ)
- Gateway: background service (Neonize)
- MinIO: http://localhost:9001

Stop all services:

```bash
just down
```

## Docker Smoke + DR Baseline

Run migration/service smoke:

```bash
just smoke-docker
```

Run backup/restore smoke:

```bash
just smoke-dr-restore
```

Run both:

```bash
just smoke-all
```

See also: `infra/compose/DR_RUNBOOK.md`.

## Hot Reload
- Frontend: Next.js HMR (`next dev`) in container.
- Backend API: `uvicorn --reload` in container.
- Worker: `watchfiles` restarts `rq worker` on Python changes.
- Gateway: `watchfiles` restarts Neonize bridge on Python changes.
- Source code is bind-mounted into containers.

## WhatsApp Session Persistence
- Gateway stores Neonize auth/session state under the repo-local `data/gateway/session` bind mount.
- Session DB path is `NEONIZE_DATABASE_PATH=/data/neonize.db`.
- Restarting containers keeps the WhatsApp session; `just reset-whatsapp-session` resets it.

## Next Step
1. Data model + first Alembic migrations
2. Auth + RBAC baseline
3. OpenAPI contract + TS client generation flow
4. Ingest -> process -> retrieve -> reply pipeline
