from __future__ import annotations

from functools import cached_property

from huggingface_hub import login
from sentence_transformers import SentenceTransformer

from app.core.config import settings


class EmbeddingGemmaService:
    @cached_property
    def model(self) -> SentenceTransformer:
        if settings.huggingface_token:
            login(token=settings.huggingface_token, add_to_git_credential=False)
        return SentenceTransformer(settings.embedding_model_id, device=settings.embedding_device)

    def warmup(self) -> None:
        _ = self.embed_document("MemoryOS embedding warmup")

    def embed_query(self, text: str) -> list[float]:
        vector = self.model.encode_query(text, normalize_embeddings=True)
        return vector.tolist()

    def embed_document(self, text: str) -> list[float]:
        vector = self.model.encode_document(text, normalize_embeddings=True)
        return vector.tolist()

    def similarity(self, left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        return float(sum(a * b for a, b in zip(left, right)))


embedding_service = EmbeddingGemmaService()
