from __future__ import annotations

from functools import cached_property

from sentence_transformers import CrossEncoder, SentenceTransformer

from app.core.config import settings


class EmbeddingService:
    """Sentence-Transformers embedding service compatible with any ST model."""

    @cached_property
    def model(self) -> SentenceTransformer:
        return SentenceTransformer(settings.embedding_model_id, device=settings.embedding_device)

    @cached_property
    def reranker(self) -> CrossEncoder:
        return CrossEncoder(settings.reranker_model_id, device=settings.reranker_device)

    def warmup_embeddings(self) -> None:
        _ = self.embed_document("MemoryOS embedding warmup")

    def warmup_reranker(self) -> None:
        if not settings.reranker_enabled:
            return
        _ = self.rerank("MemoryOS reranker warmup", ["MemoryOS reranker warmup"])

    def warmup(self) -> None:
        self.warmup_embeddings()
        self.warmup_reranker()

    def embed_query(self, text: str) -> list[float]:
        vector = self.model.encode(text, normalize_embeddings=True)
        return vector.tolist()

    def embed_document(self, text: str) -> list[float]:
        vector = self.model.encode(text, normalize_embeddings=True)
        return vector.tolist()

    def similarity(self, left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        return float(sum(a * b for a, b in zip(left, right)))

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not settings.reranker_enabled or not documents:
            return []
        pairs = [(query, document) for document in documents]
        scores = self.reranker.predict(pairs, show_progress_bar=False)
        if hasattr(scores, "tolist"):
            return [float(score) for score in scores.tolist()]
        return [float(score) for score in scores]


embedding_service = EmbeddingService()
