# Gateway Scaffold

WhatsApp gateway adapter scaffold (ingest/dispatch transport layer).

## Raw Event Persistence Rule

When mapping Neonize events, include the full provider event payload as `raw_event` in the backend inbound contract.
This payload is stored in Postgres (`message_versions.raw_event` JSONB) for audit/debug/replay.

## Neonize Hook

`src/neonize_bridge.py` wires Neonize callbacks:
- `ConnectedEv` -> gateway connected log
- `MessageEv` -> map event -> POST `/gateway/inbound`

Entry point: `src/app.py`

Environment variables:
- `GATEWAY_SESSION_NAME` (default `kuuna-gateway`)
- `BACKEND_BASE_URL` (default `http://backend:8000`)
- `GATEWAY_SERVICE_TOKEN` (optional)
- `NEONIZE_DATABASE_PATH` (default `/data/neonize.db` in Docker)

## Sentry

- Sentry project: `kuuna-gateway`
- Default CLI config in `services/gateway/.sentryclirc`
- DSN env var in `infra/env/gateway.env.example` (`SENTRY_DSN`)

For Docker dev, bind-mount source code and keep the Neonize auth/session DB in the repo-local `data/gateway/session` path mounted to `/data`.
