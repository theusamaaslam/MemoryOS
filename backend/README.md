# MemoryOS Backend

FastAPI backend for MemoryOS. This starter ships:

- `REST API` for auth, memory operations, ingestion, graph, and reflection
- `MCP-style tool endpoints` for agent integration
- `Conversation ledger` APIs and MCP tools for durable tenant-visible threads
- Postgres-backed auth, events, memories, and graph persistence
- Redis-backed session memory
- provider abstraction for OpenAI, Anthropic, Gemini, and Groq
- real `EmbeddingGemma` embeddings for retrieval
- `pgvector`-backed semantic similarity search for durable memory recall
- token-light heuristic reflection fallback for local development
- async reflection queue support with a Redis-backed worker
- Prometheus metrics and JSON request logging
- org/app ownership and admin-gated API-key/app management
- request rate limiting and secure response headers

## Run

```bash
cd backend
python -m uvicorn app.main:app --reload
```

## Notes

- On startup the service bootstraps Postgres schema and verifies Redis connectivity.
- On startup the service also warms the configured EmbeddingGemma model so deployment fails fast if the model or Hugging Face token is misconfigured.
- Real provider clients are available for OpenAI, Anthropic, Gemini, and Groq. The heuristic provider remains available only as an explicit offline fallback.
- Use `POST /api/v1/memory/reflect/async` to queue reflection work and `GET /api/v1/memory/jobs/{job_id}` to inspect status.
- Login now returns access and refresh tokens, and the worker retries failed jobs before dead-lettering them.
- Owners/admins can create apps and API keys under their organization through the auth routes.
- Owners/admins can also list org users and update member roles.
- OpenAPI docs are exposed by FastAPI at `/docs`.
- Conversation runtime now persists turns, retrieval traces, audits, tool invocations, reviewable memory candidates, and admin graph merge actions through a shared REST/MCP service layer.
