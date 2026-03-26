# MemoryOS Dashboard Roadmap

## Goal

Turn the current frontend into an operational control surface for MCP-first agents.

The dashboard should make four things easy:

1. See what the agent knows
2. See what happened in conversations
3. Control what gets promoted into durable memory
4. Repair retrieval, graph quality, and knowledge freshness over time

This roadmap assumes:

- ingestion stays in the dashboard, not MCP
- MCP remains the primary runtime interface for agents
- REST remains the operational surface for the dashboard
- trust and observability matter more than flashy chat UI

## Product Principles

### 1. Evidence Before Confidence

If the agent makes a factual claim, the UI should be able to show:

- which memories were used
- which document chunks were used
- which graph relations influenced retrieval
- whether the answer looked well-grounded or weak

### 2. Reviewable Learning

The system should not silently learn everything.

The dashboard needs to make it obvious:

- what was remembered
- what is pending review
- what became shared memory
- what was rejected, marked stale, or merged away

### 3. Tenant-First Operations

The dashboard should treat the tenant as the main operating unit.

Admins need to answer questions like:

- What kinds of conversations are happening this week?
- Which agents are improving?
- Where are hallucination risks coming from?
- Which memories are helping, stale, duplicated, or conflicting?

### 4. Fast Path For Common Work

The most common operator loops should take one or two clicks:

- ingest a source
- inspect a bad answer
- mark a memory wrong
- approve a candidate
- merge duplicate entities
- rebuild a graph

## Current Frontend Baseline

Today the frontend already has a useful foundation:

- [`App.tsx`](C:/Users/usama/Downloads/Memory/frontend/src/App.tsx)
- [`Dashboard.tsx`](C:/Users/usama/Downloads/Memory/frontend/src/pages/Dashboard.tsx)
- [`Admin.tsx`](C:/Users/usama/Downloads/Memory/frontend/src/pages/Admin.tsx)
- [`Layout.tsx`](C:/Users/usama/Downloads/Memory/frontend/src/components/Layout.tsx)
- [`GraphView.tsx`](C:/Users/usama/Downloads/Memory/frontend/src/components/GraphView.tsx)
- [`api.ts`](C:/Users/usama/Downloads/Memory/frontend/src/lib/api.ts)

Right now it behaves more like a workbench than a full control room, which is a good starting point.

## Target Information Architecture

Use a two-zone product:

### Workbench

Used by builders, operators, and support engineers working on one agent or app.

Recommended routes:

- `/`
- `/conversations`
- `/knowledge`
- `/memory`
- `/graph`

### Control Room

Used by tenant admins and platform owners.

Recommended routes:

- `/admin`
- `/admin/conversations`
- `/admin/review`
- `/admin/evals`
- `/admin/access`

If you want to move gradually, keep the existing `Dashboard` and `Admin` pages but add internal tabs first, then split them into dedicated routes later.

## Page-By-Page Roadmap

## 1. Workbench Home

### Purpose

Give one clear operating view of the currently selected tenant, app, user, and conversation.

### Main panels

- Scope header
- Health cards
- Quick actions
- Recent activity rail
- Recall lab preview
- Graph preview
- Candidate summary

### Components

- `ScopeHeader`
- `ScopePicker`
- `HealthCardGrid`
- `QuickActionBar`
- `RecentActivityFeed`
- `RecallPreviewCard`
- `GraphPreviewCard`
- `CandidateSummaryCard`
- `SyncStatusChip`

### Key actions

- start or switch a conversation
- ingest knowledge
- run reflection
- open the latest answer trace
- jump into graph repair

### Real-life example

A support lead opens the workbench for the `acme-support` agent and immediately sees:

- 3 pending memory candidates
- 2 stale policy sources
- 1 duplicate graph cluster around `Refund API`
- 7 billing conversations today with elevated risk

That turns the homepage into an operator cockpit instead of a static dashboard.

## 2. Conversations Page

### Purpose

Show every conversation as a structured, filterable operating record.

### Main panels

- filter bar
- conversation table
- thread viewer
- answer trace drawer
- classification panel

### Components

- `ConversationFilterBar`
- `ConversationTable`
- `ConversationStatusPill`
- `ConversationThread`
- `TurnCard`
- `ToolInvocationTimeline`
- `AnswerTraceDrawer`
- `ClassificationPanel`
- `ConversationActionBar`

### Filters

- agent
- user
- date range
- topic
- conversation type
- escalation state
- satisfaction
- hallucination suspicion
- memory impact

### Key actions

- open full thread
- inspect retrieved memories
- inspect answer audit
- re-run reflection
- rebuild graph for this conversation
- promote or reject candidate memories generated from this thread

### Real-life example

An admin sees a conversation marked `support`, `billing`, and `possible_hallucination`.
They open the thread, inspect the retrieval trace, notice a stale policy chunk was used, mark that source stale, reject the bad candidate, and re-run graph rebuild.

## 3. Knowledge Studio

### Purpose

Make ingestion and source lifecycle management a first-class dashboard workflow.

### Main panels

- ingestion composer
- source inventory
- source detail view
- chunk preview
- ingestion jobs
- freshness controls

### Components

- `KnowledgeIngestionComposer`
- `UploadDropzone`
- `ManualTextComposer`
- `SourceInventoryTable`
- `SourceDetailPanel`
- `ChunkPreviewList`
- `IngestionJobList`
- `FreshnessPolicyEditor`
- `SourceActionBar`

### Key actions

- upload PDF, DOCX, PPTX, XLSX, CSV, HTML, JSON, XML, or text
- paste manual text
- preview extracted chunks before or after indexing
- reindex a source
- delete a source
- mark source stale
- schedule freshness review

### Real-life example

An HR manager uploads a new handbook PDF. The dashboard shows:

- parser used
- total chunks created
- chunk preview
- extracted section titles
- candidate graph entities like `Vacation Policy` and `Carryover`

Later, when the policy changes, they open the source, click `Reindex`, and the agent starts using the updated policy.

## 4. Memory Review Inbox

### Purpose

Control what the system learns over time.

### Main panels

- pending candidate list
- scope breakdown
- evidence preview
- review history
- memory conflicts

### Components

- `CandidateQueue`
- `CandidateCard`
- `EvidencePreviewPanel`
- `ScopeSelector`
- `CandidateReviewForm`
- `ConflictBanner`
- `ReviewHistoryPanel`
- `MemoryDiffPanel`

### Key actions

- approve candidate
- reject candidate
- edit wording before approval
- change scope from `app` to `user`
- mark duplicate
- merge with existing memory

### Real-life example

The system proposes:

`Refunds above $500 require manager approval`

The reviewer sees that it appeared in four separate conversations, checks the evidence, approves it as shared app memory, and now future refund conversations benefit from it.

## 5. Memory Explorer

### Purpose

Inspect what durable memory currently exists and why.

### Main panels

- memory table
- memory detail side panel
- provenance and history
- usage analytics

### Components

- `MemoryTable`
- `MemoryDetailPanel`
- `MemoryProvenanceTrail`
- `UsageSparkline`
- `MemoryTagCloud`
- `MemoryActionBar`

### Filters

- scope
- layer
- source
- confidence
- freshness
- approval state
- last used

### Key actions

- mark wrong
- mark stale
- forget
- downscope
- upscope
- inspect conversations that used this memory

### Real-life example

An operations lead opens a shared app memory entry about onboarding policy, sees it has not been used in 90 days, confirms the process changed, and marks it stale so retrieval stops prioritizing it.

## 6. Graph Studio

### Purpose

Turn the graph into a practical repair and exploration tool, not just a visualization.

### Main panels

- graph canvas
- entity inspector
- relation inspector
- duplicate cluster queue
- evidence sidebar

### Components

- `GraphCanvas`
- `GraphToolbar`
- `EntityInspector`
- `RelationInspector`
- `EvidenceSidebar`
- `DuplicateClusterPanel`
- `MergeEntityDialog`
- `SubgraphBreadcrumbs`

### Key actions

- search entity
- focus subgraph
- inspect evidence ids
- merge aliases
- remove weak relation
- rebuild graph from conversation evidence
- highlight graph neighborhoods used during retrieval

### Real-life example

A support team has three nodes:

- `Refund API`
- `Refund Service API`
- `Refund Endpoint`

An admin selects all three, reviews supporting evidence, merges them into one canonical entity, and retrieval quality improves immediately.

## 7. Control Room Overview

### Purpose

Give tenant admins an operational summary across all agents and conversations.

### Main panels

- platform health cards
- conversation volume chart
- groundedness trend
- memory growth
- duplicate graph clusters
- stale source alerts
- top failing intents

### Components

- `OpsMetricGrid`
- `ConversationVolumeChart`
- `GroundednessTrendChart`
- `MemoryGrowthChart`
- `GraphHealthCard`
- `SourceFreshnessAlertList`
- `FailureIntentTable`

### Key actions

- jump to noisy conversations
- jump to pending reviews
- jump to stale sources
- jump to graph cleanup

### Real-life example

A tenant admin sees that `webhook authentication` conversations are rising fast and groundedness dropped after a new docs upload. They jump straight to the knowledge source and reindex it.

## 8. Evals And Reliability Center

### Purpose

Make answer quality measurable instead of anecdotal.

### Main panels

- groundedness scorecards
- retrieval quality metrics
- source freshness metrics
- candidate approval rate
- abstention rate
- contradiction alerts

### Components

- `EvalScorecardGrid`
- `RetrievalQualityTable`
- `GroundednessTrendChart`
- `AbstentionRateCard`
- `ContradictionAlertPanel`
- `RegressionRunList`

### Key actions

- run replay evaluations
- compare before and after an ingestion
- compare before and after graph merge
- inspect low-confidence answer clusters

### Real-life example

After uploading new API docs, the team runs a replay set of 100 historical questions and sees groundedness improve while hallucination-risk drops.

## 9. Access And Policy Page

### Purpose

Give admins control over who can see, review, edit, and promote tenant knowledge.

### Main panels

- members
- roles
- API keys
- agent policies
- memory policies

### Components

- `MemberDirectory`
- `RoleEditor`
- `ApiKeyTable`
- `AgentPolicyEditor`
- `MemoryPolicyRules`

### Policy examples

- never promote PII into shared app memory
- route `preference` candidates to user memory
- require manual review for `policy` and `security` memories
- auto-mark ingestion sources stale after 90 days unless reviewed

## Shared Component Inventory

These shared building blocks should be created early because they will be reused everywhere:

- `FilterBar`
- `SearchInput`
- `EntityChip`
- `ScopeChip`
- `StatusPill`
- `ConfidenceBadge`
- `EvidenceList`
- `TraceCard`
- `SidePanel`
- `Drawer`
- `EmptyState`
- `ErrorState`
- `LoadingSkeleton`
- `MetricCard`
- `ActionMenu`
- `ConfirmDialog`
- `TimestampLabel`

## Backend Capabilities Already Available

The new dashboard should immediately consume the backend work already added:

- conversation runtime and trace APIs in [`conversations.py`](C:/Users/usama/Downloads/Memory/backend/app/api/routes/conversations.py)
- shared service logic in [`conversations.py`](C:/Users/usama/Downloads/Memory/backend/app/services/conversations.py)
- recall, graph, timeline, and ingestion in [`memory.py`](C:/Users/usama/Downloads/Memory/backend/app/api/routes/memory.py)
- graph-aware retrieval and ingestion in [`memory.py`](C:/Users/usama/Downloads/Memory/backend/app/services/memory.py)

Already usable today:

- start conversation
- send message
- get conversation
- list conversations
- classify conversation
- explain answer
- list memory candidates
- approve or reject candidates
- merge entities
- rebuild graph
- ingest text and files
- view graph
- view timeline
- run recall

## API Gaps To Add Next

These are the next REST endpoints that will unlock the strongest dashboard features:

### Knowledge Studio

- `GET /api/v1/knowledge/sources`
- `GET /api/v1/knowledge/sources/{source_id}`
- `GET /api/v1/knowledge/sources/{source_id}/chunks`
- `POST /api/v1/knowledge/sources/{source_id}/reindex`
- `POST /api/v1/knowledge/sources/{source_id}/mark-stale`
- `DELETE /api/v1/knowledge/sources/{source_id}`

### Memory Explorer

- `GET /api/v1/admin/memories`
- `GET /api/v1/admin/memories/{memory_id}`
- `POST /api/v1/admin/memories/{memory_id}/mark-stale`
- `POST /api/v1/admin/memories/{memory_id}/mark-wrong`
- `POST /api/v1/admin/memories/{memory_id}/forget`
- `POST /api/v1/admin/memories/{memory_id}/rescope`

### Reliability Center

- `GET /api/v1/admin/evals/overview`
- `POST /api/v1/admin/evals/replay`
- `GET /api/v1/admin/evals/runs/{run_id}`
- `GET /api/v1/admin/conflicts`

## Recommended Delivery Phases

## Phase 1: Operational Trust

Build first:

- conversations page
- answer trace drawer
- memory review inbox
- admin conversation filters

Why first:

This is the fastest path to making the product feel real and trustworthy.

## Phase 2: Knowledge Studio

Build next:

- source inventory
- ingestion composer refinement
- chunk preview
- reindex and stale workflows

Why second:

Ingestion becomes a repeatable business workflow instead of a backend endpoint.

## Phase 3: Graph Studio

Build next:

- graph inspector
- alias merge UX
- duplicate cluster queue
- graph evidence side panel

Why third:

The graph becomes maintainable and useful instead of decorative.

## Phase 4: Evals And Policy

Build next:

- eval scorecards
- contradiction alerts
- memory policies
- freshness policies

Why fourth:

This is what turns the dashboard into a serious production operations product.

## Suggested Frontend Refactor Strategy

The current codebase can evolve without a rewrite.

### Step 1

Keep the existing layout, but split current large pages into feature sections.

### Step 2

Add route-level pages for:

- conversations
- knowledge
- memory
- graph
- admin review

### Step 3

Move all API access into focused modules:

- `lib/api/conversations.ts`
- `lib/api/knowledge.ts`
- `lib/api/memory.ts`
- `lib/api/graph.ts`
- `lib/api/admin.ts`

### Step 4

Add shared UI primitives and state hooks:

- `useConversationList`
- `useConversationTrace`
- `useMemoryCandidates`
- `useKnowledgeSources`
- `useGraphInspector`

## The Features That Will Make MemoryOS Feel Better Than A Demo

- replayable answer traces
- memory approval workflows
- stale knowledge controls
- duplicate graph cleanup
- confidence and evidence visibility everywhere
- answer abstention when support is weak
- source-centric ingestion management
- tenant-wide conversation analytics
- memory conflict detection
- before-and-after quality comparisons for ingest and graph edits

## North-Star User Journey

An operations lead uploads a new policy document, watches it chunk and index, sees the graph extract new entities, notices one duplicated entity cluster, merges it, reviews two pending memory candidates, approves one shared resolution, opens a conversation where the agent answered weakly, inspects the trace, marks one stale memory wrong, re-runs retrieval, and confirms the next answer is grounded.

That is the experience MemoryOS should optimize for.
