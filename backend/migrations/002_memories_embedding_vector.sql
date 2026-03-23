ALTER TABLE memories
ADD COLUMN IF NOT EXISTS embedding_vector vector(768);

CREATE INDEX IF NOT EXISTS idx_memories_embedding_vector_cosine
ON memories
USING ivfflat (embedding_vector vector_cosine_ops)
WITH (lists = 100);
