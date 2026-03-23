# MemoryOS Architecture Notes

## Backend seams

- `app/services/memory.py`: development implementation of the four memory layers
- `app/services/jobs.py`: async reflection job orchestration
- `app/workers/run.py`: Redis-backed worker process
- `app/services/embeddings.py`: EmbeddingGemma-based query/document embeddings
- `app/services/providers.py`: provider abstraction for OpenAI, Anthropic, Gemini, and Groq
- `app/api/routes/mcp.py`: MCP-native tool interface
- `app/api/routes/memory.py`: REST APIs for direct integration and ingestion

## Production follow-up

- replace in-memory stores with Redis and Postgres repositories
- persist tenant/app metadata and richer session controls in dedicated tables
- replace heuristic provider with real structured-output LLM providers
- expand queue-backed workers for ingestion and consolidation, not only reflection
- embed OpenAPI and API explorer directly into the dashboard

## Token-light guidance

- precompute document chunks and retrieval hints offline
- use metadata filters before vector or LLM reranking
- cache summaries and graph neighborhoods
- trigger reflection asynchronously after high-signal events
