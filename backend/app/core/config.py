from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MemoryOS"
    api_prefix: str = "/api/v1"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expiry_minutes: int = 60
    refresh_token_expiry_days: int = 14
    session_ttl_seconds: int = 86400
    cors_origins: str = "http://localhost,http://127.0.0.1,http://localhost:5173"
    redis_url: str = "redis://localhost:6379/0"
    postgres_url: str = "postgresql+psycopg://memoryos:memoryos@localhost:5432/memoryos"
    default_provider: str = "heuristic"
    embedding_provider: str = "embeddinggemma"
    embedding_model_id: str = "google/embeddinggemma-300m"
    embedding_dimensions: int = 768
    embedding_device: str = "cpu"
    reranker_enabled: bool = True
    reranker_model_id: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_device: str = "cpu"
    reranker_candidate_limit: int = 24
    retrieval_graph_match_limit: int = 6
    retrieval_expansion_term_limit: int = 12
    retrieval_source_diversity_limit: int = 2
    query_rewrite_enabled: bool = True
    graph_auto_reflect_enabled: bool = True
    graph_reflect_debounce_seconds: int = 75
    graph_periodic_scan_seconds: int = 120
    graph_periodic_refresh_seconds: int = 600
    graph_evidence_limit: int = 48
    graph_max_nodes: int = 18
    graph_max_edges: int = 24
    huggingface_token: str | None = None
    rate_limit_per_minute: int = 120
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 2
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-5-sonnet-latest"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    job_max_retries: int = 3
    job_retry_delay_seconds: int = 10
    environment: str = "development"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="MEMORYOS_")


settings = Settings()
