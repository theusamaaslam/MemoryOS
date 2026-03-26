const API_PREFIX = "/api/v1";

export type Scope = {
  org_id: string;
  app_id: string;
  user_id: string;
  session_id: string;
};

export type MemoryScope = "conversation" | "user" | "app";

export type TokenPair = {
  access_token: string;
  refresh_token: string;
};

export type CurrentUser = {
  user_id: string;
  email?: string | null;
  org_id: string;
  role: string;
};

export type TextIngestionPayload = {
  source_type: string;
  source_name: string;
  source_uri?: string;
  content: string;
  tags?: string[];
  metadata?: Record<string, unknown>;
};

export type FileIngestionPayload = {
  file: File;
  source_name?: string;
  tags?: string[];
  metadata?: Record<string, unknown>;
};

export type IngestionResult = {
  job_id: string;
  chunks_received: number;
  status: string;
  parser?: string;
  source_type?: string;
  chunking_strategy?: string;
  source_id?: string;
  source_status?: string;
  skipped?: boolean;
  chunks_created?: number;
  chunks_updated?: number;
  chunks_removed?: number;
};

export type SessionSummary = {
  session_id: string;
  last_activity_at?: string | null;
  memory_count: number;
  event_count: number;
  title?: string | null;
  status?: string | null;
  agent_id?: string | null;
};

export type GraphEvidencePreview = {
  evidence_id: string;
  layer: string;
  kind: string;
  title: string;
  excerpt: string;
  source: string;
  memory_scope: MemoryScope;
  created_at: string;
};

export type GraphSummary = {
  node_count: number;
  edge_count: number;
  evidence_count: number;
  source_count: number;
  orphan_node_count: number;
  duplicate_label_count: number;
  ungrounded_node_count: number;
  ungrounded_edge_count: number;
  source_names: string[];
};

export type GraphNodeRecord = {
  node_id: string;
  label: string;
  node_type: string;
  confidence: number;
  evidence_ids: string[];
  metadata: Record<string, unknown>;
  memory_scope: MemoryScope;
  scope_ref?: string | null;
  conversation_id?: string | null;
  evidence_preview: GraphEvidencePreview[];
};

export type GraphEdgeRecord = {
  edge_id: string;
  from_node: string;
  to_node: string;
  relation: string;
  confidence: number;
  evidence_ids: string[];
  metadata: Record<string, unknown>;
  memory_scope: MemoryScope;
  scope_ref?: string | null;
  conversation_id?: string | null;
  evidence_preview: GraphEvidencePreview[];
};

export type GraphResult = {
  memory_scope: MemoryScope;
  scope_counts: Record<string, { nodes: number; edges: number }>;
  summary: GraphSummary;
  nodes: GraphNodeRecord[];
  edges: GraphEdgeRecord[];
};

export type RecallItem = {
  memory_id: string;
  layer: string;
  content: string;
  confidence: number;
  tags: string[];
  metadata: Record<string, unknown>;
  created_at: string;
};

export type RecallTrace = {
  query: string;
  rewritten_query?: string | null;
  query_rewrite_applied?: boolean;
  query_rewrite_reason?: string | null;
  query_mode: string;
  query_intent?: string;
  scope_bias?: string;
  graph_strategy?: string;
  grounding_policy?: string;
  freshness_bias?: string;
  preferred_layers?: string[];
  expansion_terms?: string[];
  layers_consulted: string[];
  ranking_factors: string[];
  reasons: string[];
  graph_matches: number;
  graph_expansions: number;
  retrieval_hint_matches: number;
};

export type RecallResult = {
  items: RecallItem[];
  trace: RecallTrace;
};

export type ConversationLabel = {
  conversation_type: string;
  topic: string;
  outcome: string;
  escalation_state: string;
  satisfaction: string;
  hallucination_suspected: boolean;
  risk_level: string;
  memory_impact_score: number;
  metadata: Record<string, unknown>;
};

export type ConversationMessage = {
  message_id: string;
  role: string;
  content: string;
  citations: Array<Record<string, unknown>>;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type ConversationTurn = {
  turn_id: string;
  turn_index: number;
  status: string;
  summary: string;
  messages: ConversationMessage[];
  created_at: string;
  updated_at: string;
};

export type Conversation = {
  conversation_id: string;
  org_id: string;
  app_id: string;
  user_id: string;
  agent_id: string;
  title: string;
  status: string;
  summary: string;
  message_count: number;
  last_message_at?: string | null;
  created_at: string;
  updated_at: string;
  label: ConversationLabel;
  turns: ConversationTurn[];
};

export type ConversationSummary = {
  conversation_id: string;
  app_id: string;
  user_id: string;
  agent_id: string;
  title: string;
  status: string;
  summary: string;
  message_count: number;
  last_message_at?: string | null;
  created_at: string;
  label: ConversationLabel;
};

export type ConversationListResult = {
  items: ConversationSummary[];
};

export type StartConversationPayload = {
  app_id?: string;
  user_id?: string;
  title?: string;
  description?: string;
  metadata?: Record<string, unknown>;
};

export type ConversationCitation = {
  memory_id: string;
  layer: string;
  content: string;
  score: number;
};

export type SendConversationMessageResult = {
  conversation: ConversationSummary;
  user_message: ConversationMessage;
  assistant_message: ConversationMessage;
  citations: ConversationCitation[];
  supported: boolean;
  abstained: boolean;
  trace_id: string;
  audit_id: string;
};

export type ExplainAnswerResult = {
  trace_id: string;
  query: string;
  items: Array<Record<string, unknown>>;
  trace: Record<string, unknown>;
  audit: Record<string, unknown>;
};

export type ConversationTraceRecord = {
  trace_id: string;
  message_id: string;
  query: string;
  items: Array<Record<string, unknown>>;
  trace: Record<string, unknown>;
  created_at: string;
};

export type ConversationAuditRecord = {
  audit_id: string;
  turn_id: string;
  provider: string;
  model_name: string;
  latency_ms: number;
  confidence: number;
  supported: boolean;
  abstained: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type ToolInvocationRecord = {
  invocation_id: string;
  turn_id?: string | null;
  tool_name: string;
  payload: Record<string, unknown>;
  result: Record<string, unknown>;
  created_at: string;
};

export type ConversationTraceResult = {
  conversation: Conversation;
  traces: ConversationTraceRecord[];
  audits: ConversationAuditRecord[];
  tool_invocations: ToolInvocationRecord[];
};

export type MemoryCandidate = {
  candidate_id: string;
  org_id: string;
  app_id: string;
  user_id: string;
  conversation_id: string;
  memory_scope: string;
  layer: string;
  content: string;
  status: string;
  confidence: number;
  source_memory_ids: string[];
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type MemoryCandidateListResult = {
  items: MemoryCandidate[];
};

export type AppRecord = {
  app_id: string;
  org_id: string;
  name: string;
};

export type ApiKeyResult = {
  key_id: string;
  name: string;
  app_id: string;
  api_key: string;
};

export type McpToolDescriptor = {
  name: string;
  category?: string;
  description: string;
  required_fields?: string[];
  optional_fields?: string[];
};

export type OrgUser = {
  user_id: string;
  email: string;
  full_name: string;
  org_id: string;
  role: string;
};

async function readErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const payload = await response.json();
      if (payload && typeof payload.detail === "string" && payload.detail.trim()) {
        return payload.detail;
      }
    }
  } catch {
    // Fall through to status-aware fallback handling below.
  }
  if ([502, 503, 504].includes(response.status)) {
    return `${fallback} (${response.status} ${response.statusText}). The dashboard could not reach the backend service.`;
  }
  if (response.status && response.statusText) {
    return `${fallback} (${response.status} ${response.statusText})`;
  }
  return fallback;
}

function buildQueryString(params: Record<string, string | number | undefined | null>) {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    searchParams.set(key, String(value));
  });
  const query = searchParams.toString();
  return query ? `?${query}` : "";
}

export async function login(email: string, password: string): Promise<TokenPair> {
  const response = await fetch(`${API_PREFIX}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password })
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Login failed"));
  }
  return response.json();
}

export async function refresh(refreshToken: string): Promise<TokenPair> {
  const response = await fetch(`${API_PREFIX}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken })
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Session refresh failed"));
  }
  return response.json();
}

export async function me(token: string): Promise<CurrentUser> {
  const response = await fetch(`${API_PREFIX}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to load current user"));
  }
  return response.json();
}

export async function fetchGraph(token: string, scope: Scope, memoryScope: MemoryScope = "app"): Promise<GraphResult> {
  const response = await fetch(`${API_PREFIX}/memory/graph`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ scope, memory_scope: memoryScope })
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to load graph"));
  }
  return response.json();
}

export async function fetchTimeline(token: string, scope: Scope, memoryScope: MemoryScope = "app") {
  const response = await fetch(`${API_PREFIX}/memory/timeline`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ scope, memory_scope: memoryScope })
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to load timeline"));
  }
  return response.json();
}

export async function fetchSessions(token: string, scope: Scope): Promise<{ items: SessionSummary[] }> {
  const response = await fetch(`${API_PREFIX}/memory/sessions`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ scope })
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to load sessions"));
  }
  return response.json();
}

export async function recallMemories(
  token: string,
  scope: Scope,
  payload: { query: string; top_k?: number; include_layers?: string[] },
): Promise<RecallResult> {
  const response = await fetch(`${API_PREFIX}/memory/recall`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      scope,
      query: payload.query,
      top_k: payload.top_k ?? 5,
      include_layers: payload.include_layers
    })
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to run recall"));
  }
  return response.json();
}

export async function ingestDocumentText(token: string, scope: Scope, payload: TextIngestionPayload): Promise<IngestionResult> {
  const response = await fetch(`${API_PREFIX}/memory/ingest`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      scope,
      source_type: payload.source_type,
      source_name: payload.source_name,
      source_uri: payload.source_uri,
      content: payload.content,
      tags: payload.tags ?? [],
      metadata: payload.metadata ?? {}
    })
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to ingest document"));
  }
  return response.json();
}

export async function ingestDocumentFile(token: string, scope: Scope, payload: FileIngestionPayload): Promise<IngestionResult> {
  const formData = new FormData();
  formData.append("org_id", scope.org_id);
  formData.append("app_id", scope.app_id);
  formData.append("user_id", scope.user_id);
  formData.append("session_id", scope.session_id);
  formData.append("source_name", payload.source_name ?? "");
  formData.append("tags_json", JSON.stringify(payload.tags ?? []));
  formData.append("metadata_json", JSON.stringify(payload.metadata ?? {}));
  formData.append("file", payload.file);

  const response = await fetch(`${API_PREFIX}/memory/ingest/upload`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`
    },
    body: formData
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to ingest uploaded document"));
  }
  return response.json();
}

export async function reflectSession(token: string, scope: Scope, memoryScope: MemoryScope = "app") {
  const response = await fetch(`${API_PREFIX}/memory/reflect`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      scope,
      memory_scope: memoryScope
    })
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to run reflection"));
  }
  return response.json();
}

export async function listConversations(
  token: string,
  options: { app_id?: string; limit?: number } = {},
): Promise<ConversationListResult> {
  const response = await fetch(
    `${API_PREFIX}/conversations${buildQueryString({ app_id: options.app_id, limit: options.limit ?? 80 })}`,
    {
      headers: { Authorization: `Bearer ${token}` },
    },
  );
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to load conversations"));
  }
  return response.json();
}

export async function startConversation(
  token: string,
  agentId: string,
  payload: StartConversationPayload,
): Promise<Conversation> {
  const response = await fetch(`${API_PREFIX}/agents/${encodeURIComponent(agentId)}/conversations`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      app_id: payload.app_id,
      user_id: payload.user_id,
      title: payload.title,
      description: payload.description,
      metadata: payload.metadata ?? {},
    }),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to start conversation"));
  }
  return response.json();
}

export async function getConversation(token: string, conversationId: string): Promise<Conversation> {
  const response = await fetch(`${API_PREFIX}/conversations/${encodeURIComponent(conversationId)}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to load conversation"));
  }
  return response.json();
}

export async function closeConversation(
  token: string,
  conversationId: string,
  reason?: string,
): Promise<Conversation> {
  const response = await fetch(`${API_PREFIX}/conversations/${encodeURIComponent(conversationId)}/close`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ reason: reason ?? "" }),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to close conversation"));
  }
  return response.json();
}

export async function sendConversationMessage(
  token: string,
  conversationId: string,
  payload: { content: string; top_k?: number; metadata?: Record<string, unknown> },
): Promise<SendConversationMessageResult> {
  const response = await fetch(`${API_PREFIX}/conversations/${encodeURIComponent(conversationId)}/messages`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      content: payload.content,
      top_k: payload.top_k ?? 5,
      metadata: payload.metadata ?? {},
    }),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to send message"));
  }
  return response.json();
}

export async function classifyConversation(token: string, conversationId: string): Promise<ConversationLabel> {
  const response = await fetch(`${API_PREFIX}/conversations/classify`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ conversation_id: conversationId }),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to classify conversation"));
  }
  return response.json();
}

export async function explainConversation(token: string, conversationId: string): Promise<ExplainAnswerResult> {
  const response = await fetch(`${API_PREFIX}/conversations/${encodeURIComponent(conversationId)}/explain`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to load answer trace"));
  }
  return response.json();
}

export async function listTenantConversations(
  token: string,
  orgId: string,
  options: { app_id?: string; user_id?: string; limit?: number } = {},
): Promise<ConversationListResult> {
  const response = await fetch(
    `${API_PREFIX}/admin/tenants/${encodeURIComponent(orgId)}/conversations${buildQueryString({
      app_id: options.app_id,
      user_id: options.user_id,
      limit: options.limit ?? 120,
    })}`,
    {
      headers: { Authorization: `Bearer ${token}` },
    },
  );
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to load tenant conversations"));
  }
  return response.json();
}

export async function getConversationTrace(token: string, conversationId: string): Promise<ConversationTraceResult> {
  const response = await fetch(`${API_PREFIX}/admin/conversations/${encodeURIComponent(conversationId)}/trace`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to load conversation trace"));
  }
  return response.json();
}

export async function listMemoryCandidates(
  token: string,
  options: { org_id?: string; app_id?: string; status?: string; limit?: number } = {},
): Promise<MemoryCandidateListResult> {
  const response = await fetch(
    `${API_PREFIX}/admin/memory-candidates${buildQueryString({
      org_id: options.org_id,
      app_id: options.app_id,
      status: options.status,
      limit: options.limit ?? 150,
    })}`,
    {
      headers: { Authorization: `Bearer ${token}` },
    },
  );
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to load memory candidates"));
  }
  return response.json();
}

export async function approveMemoryCandidate(token: string, candidateId: string, reason?: string): Promise<MemoryCandidate> {
  const response = await fetch(`${API_PREFIX}/admin/memory-candidates/${encodeURIComponent(candidateId)}/approve`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ reason: reason ?? "" }),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to approve memory candidate"));
  }
  return response.json();
}

export async function rejectMemoryCandidate(token: string, candidateId: string, reason?: string): Promise<MemoryCandidate> {
  const response = await fetch(`${API_PREFIX}/admin/memory-candidates/${encodeURIComponent(candidateId)}/reject`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ reason: reason ?? "" }),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to reject memory candidate"));
  }
  return response.json();
}

export async function rebuildConversationGraph(token: string, conversationId: string): Promise<{ status: string; summary?: string }> {
  const response = await fetch(`${API_PREFIX}/admin/graph/append`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ conversation_id: conversationId }),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to append graph update"));
  }
  return response.json();
}

export async function listApps(token: string): Promise<AppRecord[]> {
  const response = await fetch(`${API_PREFIX}/auth/apps`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to load applications"));
  }
  return response.json();
}

export async function createApiKey(
  token: string,
  payload: { org_id: string; app_id: string; name: string },
): Promise<ApiKeyResult> {
  const response = await fetch(`${API_PREFIX}/auth/api-keys`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to create API key"));
  }
  return response.json();
}

export async function fetchMcpTools(token: string): Promise<McpToolDescriptor[]> {
  const response = await fetch(`${API_PREFIX}/mcp/tools`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to load MCP tools"));
  }
  const payload = await response.json();
  return Array.isArray(payload?.tools) ? payload.tools : [];
}

export async function listOrgUsers(token: string): Promise<OrgUser[]> {
  const response = await fetch(`${API_PREFIX}/auth/users`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, "Failed to load organization users"));
  }
  return response.json();
}
