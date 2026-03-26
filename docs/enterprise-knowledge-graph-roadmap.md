# Enterprise Knowledge Graph Roadmap

## Problem To Fix

The product should treat the conversation/event stream as the source of truth and the graph as a grounded, reviewable projection built later when it adds value.

That means:

- events remain append-only and readable in the timeline
- graph writes happen through reflection, promotion, or rebuild workflows
- app, user, and conversation graph slices stay separate
- every node and edge should point back to evidence
- operators need graph health signals before they trust the graph

## Direction Inspired By Docling, LightRAG, and Cognee

### Docling-inspired ingestion layer

Use document parsing as a first-class pipeline, not just file upload.

- preserve layout-aware metadata like headings, pages, tables, and sheet names
- keep parser and chunking provenance on every stored chunk
- support re-index and freshness review per source
- later extension: OCR, structured PDF layout, image/table extraction, and source quality scoring

### LightRAG-inspired retrieval layer

Use the graph as a retrieval expansion and grounding tool, not as a decorative visualization.

- query-time graph neighborhood expansion
- evidence-first node and relation selection
- local/global/hybrid retrieval modes
- graph health metrics that explain why the graph should or should not influence recall
- later extension: subgraph ranking, path scoring, and graph-aware reranker features

### Cognee-inspired memory layer

Keep the developer mental model simple while making operations much stronger.

- event stream
- reflection artifact
- candidate promotion
- durable shared memory
- inspectable graph slice

The UX should feel like:

- add knowledge
- inspect memory
- review promotions
- repair graph
- measure retrieval quality

## What Changed In This Iteration

- graph APIs now honor `memory_scope` instead of blending conversation, user, and app graphs together
- timeline items are annotated when they later become evidence for the currently selected graph slice
- graph responses now include evidence previews and health summaries
- MCP scope handling now forwards `memory_scope` correctly for remember, graph search, and reflection
- entity merge now collapses duplicate/self-loop edges after alias repair
- repeated reflection runs stop creating duplicate memory candidates for the same conversation content

## Enterprise-Grade Next Steps

### 1. Knowledge control plane

- graph health dashboard
- source inventory with stale/reindex states
- candidate inbox with approvals and reversals
- audit history for every promotion, merge, rebuild, and rejection

### 2. Safer memory governance

- promotion policies by tenant/app
- retention windows by memory scope
- PII/security classifiers before promotion
- contradiction detection between candidate memories

### 3. Retrieval quality operations

- retrieval feedback capture on each cited memory
- stale/wrong/unsafe flags on chunks and graph entities
- offline eval sets per tenant/app
- scorecards for hallucination rate, citation coverage, and source freshness

### 4. Scale and reliability

- separate workers for ingestion, reflection, graph consolidation, and evals
- dead-letter queues and replay tooling
- idempotency keys for ingest, reflect, and promotion jobs
- graph rebuild jobs per tenant/app with progress reporting

## Billing Design

Billing should be usage-based at the organization and app level, with Stripe handling invoicing and payment collection.

### Metered dimensions

- chat input tokens
- chat output tokens
- embedding tokens or characters
- ingestion bytes and parsed pages
- durable chunk storage
- retrieval queries
- reflection jobs
- graph rebuild jobs
- graph storage footprint

### Internal usage events

Every billable action should emit a durable usage event:

- `chat.completed`
- `embedding.generated`
- `ingest.completed`
- `recall.completed`
- `reflection.completed`
- `graph.rebuild.completed`

Each event should include:

- `org_id`
- `app_id`
- `conversation_id` when applicable
- meter name
- quantity
- provider
- provider cost if known
- created timestamp

### Data model

Add billing tables such as:

- `billing_customers`
- `billing_subscriptions`
- `billing_meters`
- `billing_usage_events`
- `billing_usage_rollups`
- `billing_invoices`

### Runtime integration points

- API layer records request-scoped usage
- provider layer records model/provider token counts
- ingestion pipeline records bytes, pages, chunks, and parser type
- memory/graph services record reflection and rebuild usage
- nightly rollups aggregate raw events into invoice-ready totals

### Product behavior

- hard and soft quotas per org/app
- live usage dashboard for admins
- alerts at 80%, 95%, and 100% of plan limits
- graceful degradation instead of silent failure when limits are hit

## Recommended Commercial Model

Use a hybrid plan:

- base platform fee per organization
- included monthly usage bucket
- overage on tokens, ingestion, and storage
- enterprise tier adds SSO, audit export, retention controls, and dedicated throughput

This keeps pricing understandable while matching the real cost drivers of a memory platform.
