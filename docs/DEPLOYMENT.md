# Public Deployment Guide

This guide covers deploying EasyPaper for a small group of users over the public
internet, using the hardened stack in `docker-compose.prod.yml` (Caddy auto-HTTPS
+ Postgres). For a quick local trial, use `docker-compose.yml` or the local-dev
instructions in the README instead.

## What this stack gives you

- **TLS by default** — Caddy obtains and renews Let's Encrypt certificates.
- **Only Caddy is exposed** (ports 80/443). The backend (`:8000`) and Postgres
  are on the internal Docker network, unreachable from the internet.
- **Postgres** instead of SQLite, so concurrent users don't hit "database is locked".
- **Self-registration disabled** — you create accounts explicitly.
- **MCP `/mcp` and `/api/agent` require an agent API key.**
- **Fail-fast**: with `APP_ENV=production`, the backend refuses to start if the
  JWT secret or agent API key is still a placeholder default.

## Prerequisites

- A server with Docker + Docker Compose.
- A domain name with a DNS A/AAAA record pointing at the server.
- Ports **80** and **443** open to the internet (required for TLS issuance).

## Step 1 — Backend config (`backend/config/config.yaml`)

```bash
cp backend/config/config.example.yaml backend/config/config.yaml
```

Edit it and set, at minimum:

```yaml
llm:
  api_key: "YOUR_REAL_LLM_KEY"
  base_url: "https://your-openai-compatible-endpoint/v1"
  model: "gemini-2.5-flash"

security:
  secret_key: "<paste output of: openssl rand -hex 32>"   # MUST change — prod won't start otherwise
  allow_registration: false                                # disable public sign-up
  cors_origins:
    - "https://papers.example.com"                          # your domain

agent:
  api_keys:
    - "<paste output of: openssl rand -hex 32>"             # MUST change if you use /api/agent or /mcp
```

> `database.url` can stay the SQLite default — it is overridden by the
> `DATABASE_URL` env var the compose file injects for Postgres.

Generate strong secrets:

```bash
openssl rand -hex 32   # run twice: one for secret_key, one for each agent api key
```

## Step 2 — Compose environment (`.env`)

```bash
cp .env.example .env
```

Set `DOMAIN`, `POSTGRES_PASSWORD` (a long random string), and optionally
`POSTGRES_USER` / `POSTGRES_DB`.

## Step 3 — Launch

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

First run downloads the PDF layout model and may take a few minutes. Watch logs:

```bash
docker compose -f docker-compose.prod.yml logs -f backend
```

## Step 4 — Create user accounts

Self-registration is off, so add each user explicitly:

```bash
docker compose -f docker-compose.prod.yml exec backend \
  python -m app.cli create-user alice@example.com 'a-strong-password'
```

## Step 5 — Verify

- `https://<DOMAIN>` loads the app over HTTPS (valid certificate).
- You can log in with an account created in Step 4.
- From outside the server, `http://<server-ip>:8000` is **not** reachable
  (backend is internal-only).
- `https://<DOMAIN>/mcp` without `X-Agent-Api-Key` returns 403.

## Backups

Application data lives in Postgres (knowledge base, users, tasks). Back it up
with `pg_dump`:

```bash
# One-off dump
docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U easypaper easypaper | gzip > easypaper-$(date +%F).sql.gz

# Restore
gunzip -c easypaper-2026-06-17.sql.gz | \
  docker compose -f docker-compose.prod.yml exec -T db psql -U easypaper easypaper
```

Automate with cron (daily at 03:00):

```cron
0 3 * * * cd /path/to/EasyPaper && docker compose -f docker-compose.prod.yml exec -T db pg_dump -U easypaper easypaper | gzip > /backups/easypaper-$(date +\%F).sql.gz
```

Also keep a copy of `backend/config/config.yaml` and `.env` somewhere safe (they
hold your secrets and are gitignored).

## Logs

Backend logs are written to the `backend-logs` volume (`/app/logs`) and also to
stdout. View them with:

```bash
docker compose -f docker-compose.prod.yml logs -f backend
```

## Upgrades

```bash
git pull
docker compose -f docker-compose.prod.yml up --build -d
```

Caveats to know before upgrading:

- **In-flight translation/extraction jobs are in-memory** and are lost on
  restart. Upgrade when the system is idle; users can re-submit.
- **No automatic schema migrations on Postgres.** `create_all()` creates *new
  tables*, but it does **not** alter existing tables. If a future version adds a
  column to an existing model, you must apply that change manually (or introduce
  Alembic) before upgrading. New installs are unaffected.

## Operational notes / known limits

- The backend runs as a **single uvicorn process** by design (in-memory task
  queue, rate limiter, and concurrency semaphore are per-process). Do **not** add
  `--workers`. This caps throughput — fine for a small group, not for large scale.
- PDF translation is CPU- and memory-intensive (`processing.max_concurrent`
  bounds parallelism, default 3). Size the server accordingly.
- There are no per-user usage quotas. Registration is closed, so abuse is bounded
  to the users you create — but they share your LLM API budget.
