const endpoints = [
  "POST /api/v1/auth/register",
  "POST /api/v1/auth/login",
  "POST /api/v1/memory/remember",
  "POST /api/v1/memory/recall",
  "POST /api/v1/memory/reflect",
  "POST /api/v1/memory/ingest",
  "GET /api/v1/mcp/tools"
];

export function DocsPanel() {
  return (
    <div className="docs-panel">
      <p>
        The dashboard should embed FastAPI OpenAPI docs, MCP tool references, ingestion guides, and
        copy-paste examples for direct REST and MCP usage.
      </p>
      <ul className="docs-list">
        {endpoints.map((endpoint) => (
          <li key={endpoint}>{endpoint}</li>
        ))}
      </ul>
      <pre className="code-block">
        <code>{`curl -X POST /api/v1/memory/remember \\
  -H "Authorization: Bearer <token>" \\
  -H "Content-Type: application/json"`}</code>
      </pre>
    </div>
  );
}
