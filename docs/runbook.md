# MemoryOS Runbook

## Bring the stack up

```bash
docker compose up -d --build
```

## Check service health

- Dashboard: `http://<host>/`
- API docs: `http://<host>/docs`
- Metrics: `http://<host>/metrics`
- Prometheus: `http://<host>:9090/`

## Database backups

Create a backup:

```bash
sh scripts/backup-db.sh
```

Restore a backup:

```bash
sh scripts/restore-db.sh backups/<file>.sql.gz
```

## Reflection job failures

- Check worker logs: `docker compose logs worker --tail=200`
- Dead-letter jobs remain in the `jobs` table with `status = 'dead_letter'`
- Investigate provider/API-key issues first when reflection repeatedly fails

## Admin controls

- Org owners/admins can create apps and API keys through the auth endpoints
- Org owners/admins can list users and promote/demote roles
- API endpoints are rate-limited per client IP by default

## Key env vars

- `MEMORYOS_DEFAULT_PROVIDER`
- `MEMORYOS_HUGGINGFACE_TOKEN`
- `MEMORYOS_OPENAI_API_KEY`
- `MEMORYOS_ANTHROPIC_API_KEY`
- `MEMORYOS_GEMINI_API_KEY`
- `MEMORYOS_GROQ_API_KEY`
- `MEMORYOS_CORS_ORIGINS`
