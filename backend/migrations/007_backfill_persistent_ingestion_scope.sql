UPDATE memories
SET memory_scope = 'app',
    scope_ref = app_id
WHERE source = 'ingestion'
  AND (memory_scope IS NULL OR memory_scope <> 'app');

UPDATE graph_nodes AS graph_node
SET graph_scope = 'app',
    scope_ref = graph_node.app_id
WHERE (graph_node.graph_scope IS NULL OR graph_node.graph_scope <> 'app')
  AND EXISTS (
      SELECT 1
      FROM jsonb_array_elements_text(COALESCE(graph_node.evidence_ids_json::jsonb, '[]'::jsonb)) AS evidence(memory_id)
      JOIN memories AS memory
        ON memory.memory_id = evidence.memory_id
       AND memory.org_id = graph_node.org_id
       AND memory.app_id = graph_node.app_id
      WHERE memory.source = 'ingestion'
        AND memory.memory_scope = 'app'
  );

UPDATE graph_edges AS graph_edge
SET graph_scope = 'app',
    scope_ref = graph_edge.app_id
WHERE (graph_edge.graph_scope IS NULL OR graph_edge.graph_scope <> 'app')
  AND EXISTS (
      SELECT 1
      FROM jsonb_array_elements_text(COALESCE(graph_edge.evidence_ids_json::jsonb, '[]'::jsonb)) AS evidence(memory_id)
      JOIN memories AS memory
        ON memory.memory_id = evidence.memory_id
       AND memory.org_id = graph_edge.org_id
       AND memory.app_id = graph_edge.app_id
      WHERE memory.source = 'ingestion'
        AND memory.memory_scope = 'app'
  );
