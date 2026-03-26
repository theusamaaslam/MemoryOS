# Memory Core Integration Notes

This repo is now moving toward a combined architecture:

- Docling-style ingestion:
  preserve document structure, headings, pages, sheets, tables, and chunk-level provenance instead of flattening everything into anonymous text.
- Cognee-style memory pipeline:
  keep a relational source registry that tracks documents, chunk identity, provenance, and incremental processing status alongside vector and graph retrieval.
- LightRAG-style graph evolution:
  append and merge graph updates incrementally, prune only stale evidence from affected sources, and avoid whole-graph rebuilds for normal ingestion.

## Current implementation

1. `document_sources` is the durable control-plane table for ingested knowledge.
2. Ingested chunk memories now carry stable `source_id` and `chunk_key` identity.
3. Re-ingesting an unchanged source returns `status=skipped` and does not enqueue reflection.
4. Re-ingesting a changed source upserts existing chunks, creates only new chunks, removes missing chunks, and prunes graph evidence only for removed chunk memories.
5. Reflection marks touched sources as `ready` again after graph merge completes.

## Why this matters

- Retrieval quality improves because the same document no longer turns into duplicate long-term memories on every ingest.
- Graph quality improves because stale relations are pruned only where evidence actually disappeared.
- Operator trust improves because ingestion state becomes durable and inspectable instead of implicit.

## Next steps

1. Add source inventory APIs and dashboards.
2. Add ingestion runs with per-source error reporting and connector sync status.
3. Add source-scoped targeted re-reflection so only changed sources feed graph extraction when possible.
4. Add source-aware retrieval evals for exact policy/entity lookup and multi-hop workflow questions.
