from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import settings


@dataclass(slots=True)
class ReflectionArtifact:
    summary: str
    facts: list[str]
    preferences: list[str]
    entities: list[tuple[str, str]]
    relations: list[tuple[str, str, str]]
    failures: list[str]
    resolutions: list[str]
    retrieval_hints: list[str]


@dataclass(slots=True)
class QueryRewriteResult:
    apply: bool
    rewritten_query: str
    reason: str


class LLMProvider(Protocol):
    name: str

    def reflect(self, transcript: str) -> ReflectionArtifact: ...
    def rewrite_query(self, query: str, context: str) -> QueryRewriteResult: ...


class HeuristicProvider:
    """Local fallback for offline development only."""

    name = "heuristic"

    def reflect(self, transcript: str) -> ReflectionArtifact:
        lines = [line.strip() for line in transcript.splitlines() if line.strip()]
        facts = [line for line in lines if "prefer" in line.lower() or "need" in line.lower()][:4]
        failures = [line for line in lines if "didn't" in line.lower() or "failed" in line.lower() or "error" in line.lower()][:3]
        preferences = [line for line in lines if "like" in line.lower() or "prefer" in line.lower()][:4]
        resolutions = [line for line in lines if "resolved" in line.lower() or "worked" in line.lower() or "fixed" in line.lower()][:3]
        entities = self._extract_entities(lines)
        relations = self._extract_relations(lines, entities)
        retrieval_hints = [f"Prioritize on similar query: {line[:80]}" for line in facts[:2] + failures[:1]]
        return ReflectionArtifact(
            summary=lines[-1] if lines else "No transcript available",
            facts=facts or lines[:2],
            preferences=preferences,
            entities=entities or [("User", "person"), ("Agent", "assistant")],
            relations=relations or [("User", "Agent", "interacted_with")],
            failures=failures,
            resolutions=resolutions,
            retrieval_hints=retrieval_hints,
        )

    def rewrite_query(self, query: str, context: str) -> QueryRewriteResult:
        cleaned_query = re.sub(r"\s+", " ", query).strip()
        context_terms = [term.strip(" -") for term in re.split(r"[\n,|]+", context) if term.strip()]
        high_signal_terms = [term for term in context_terms if len(term) >= 4][:3]
        if not high_signal_terms:
            return QueryRewriteResult(apply=False, rewritten_query=cleaned_query, reason="No domain context available for rewrite.")
        rewritten = f"{cleaned_query} about {'; '.join(high_signal_terms)}"
        return QueryRewriteResult(apply=True, rewritten_query=rewritten[:240], reason="Expanded vague query with available graph and source context.")

    def _extract_entities(self, lines: list[str]) -> list[tuple[str, str]]:
        pattern = re.compile(
            r"\b(?:[A-Z][a-z]+(?:[A-Z][a-z]+)+|[A-Z]{2,}(?:\s+[A-Z]{2,}){0,2}|[A-Z][a-z]+(?:\s+[A-Z][A-Za-z0-9/&-]+){1,4})\b"
        )
        blocked = {
            "The",
            "This",
            "That",
            "These",
            "Those",
            "And",
            "But",
            "For",
            "With",
            "From",
            "Into",
            "After",
            "Before",
            "During",
            "Page",
            "Section",
            "Chunk",
        }
        seen: list[tuple[str, str]] = []
        for line in lines:
            for match in pattern.finditer(line):
                label = match.group(0).strip(" .,:;()[]{}")
                if len(label) < 3 or label in blocked:
                    continue
                if not any(character.isalpha() for character in label):
                    continue
                node_type = self._guess_node_type(label)
                entity = (label, node_type)
                if entity not in seen:
                    seen.append(entity)
                if len(seen) >= 20:
                    return seen
        return seen

    def _extract_relations(self, lines: list[str], entities: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
        labels = [label for label, _ in entities]
        relations: list[tuple[str, str, str]] = []
        for line in lines:
            line_entities = [label for label in labels if label in line]
            if len(line_entities) < 2:
                continue
            relation_name = self._guess_relation(line)
            for index in range(len(line_entities) - 1):
                relation = (line_entities[index], line_entities[index + 1], relation_name)
                if relation not in relations:
                    relations.append(relation)
                if len(relations) >= 30:
                    return relations
        return relations

    def _guess_node_type(self, label: str) -> str:
        lower = label.lower()
        if any(keyword in lower for keyword in ("policy", "handbook", "manual", "document", "guide", "runbook", "playbook")):
            return "document"
        if any(keyword in lower for keyword in ("team", "department", "office", "committee", "company", "organization", "org")):
            return "organization"
        if any(keyword in lower for keyword in ("api", "mcp", "memoryos", "dashboard", "system", "service", "model")):
            return "system"
        parts = label.split()
        if 1 < len(parts) <= 3 and all(part[:1].isupper() for part in parts):
            return "person"
        return "concept"

    def _guess_relation(self, line: str) -> str:
        lower = line.lower()
        if "belongs to" in lower or "part of" in lower:
            return "belongs_to"
        if "uses" in lower or "use " in lower:
            return "uses"
        if "reports to" in lower:
            return "reports_to"
        if "works with" in lower or "connected to" in lower:
            return "connected_to"
        if "mentions" in lower or "describes" in lower:
            return "describes"
        return "related_to"


SYSTEM_PROMPT = """
You are a memory reflection engine for an AI agent platform.
Return ONLY valid JSON with this exact shape:
{
  "summary": "string",
  "facts": ["string"],
  "preferences": ["string"],
  "entities": [{"label": "string", "node_type": "string"}],
  "relations": [{"source": "string", "target": "string", "relation": "string"}],
  "failures": ["string"],
  "resolutions": ["string"],
  "retrieval_hints": ["string"]
}
Rules:
- Focus on durable memory, failures, resolutions, and retrieval improvements.
- Keep lists concise and high-signal.
- Only emit entities and relations that are explicitly supported by the provided evidence.
- Use short canonical labels copied from the source text; do not invent abstract umbrella entities.
- Prefer conservative relation names like related_to, mentions, describes, uses, depends_on, reports_to, belongs_to, part_of, connected_to.
- If the evidence is weak, omit the entity or relation rather than guessing.
- Never include markdown or code fences.
""".strip()

QUERY_REWRITE_PROMPT = """
You rewrite vague enterprise-memory search queries so retrieval performs better.
Return ONLY valid JSON with this exact shape:
{
  "apply": true,
  "rewritten_query": "string",
  "reason": "string"
}
Rules:
- Keep the user's original intent.
- Rewrite only if the query is vague, underspecified, or uses ambiguous references like this/that/it.
- Use the provided context only when it helps clarify the retrieval target.
- Optimize for retrieval across embeddings, knowledge graph expansion, and reranking.
- Keep rewritten_query concise, concrete, and under 220 characters.
- Do not answer the question.
- If no rewrite is needed, set apply to false and return the original query.
""".strip()


def _normalize_artifact(payload: dict) -> ReflectionArtifact:
    entities = [(item["label"], item["node_type"]) for item in payload.get("entities", []) if "label" in item and "node_type" in item]
    relations = [
        (item["source"], item["target"], item["relation"])
        for item in payload.get("relations", [])
        if "source" in item and "target" in item and "relation" in item
    ]
    return ReflectionArtifact(
        summary=str(payload.get("summary", "")),
        facts=[str(item) for item in payload.get("facts", [])][:10],
        preferences=[str(item) for item in payload.get("preferences", [])][:10],
        entities=entities[:20],
        relations=relations[:30],
        failures=[str(item) for item in payload.get("failures", [])][:10],
        resolutions=[str(item) for item in payload.get("resolutions", [])][:10],
        retrieval_hints=[str(item) for item in payload.get("retrieval_hints", [])][:10],
    )


def _normalize_rewrite_result(payload: dict, original_query: str) -> QueryRewriteResult:
    rewritten_query = str(payload.get("rewritten_query", "")).strip() or original_query.strip()
    apply = bool(payload.get("apply")) and rewritten_query != original_query.strip()
    return QueryRewriteResult(
        apply=apply,
        rewritten_query=rewritten_query[:240],
        reason=str(payload.get("reason", "")).strip() or "No rewrite was applied.",
    )


class BaseHTTPProvider:
    name = "base"

    def _request_with_retries(self, method: str, url: str, **kwargs) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(settings.llm_max_retries + 1):
            try:
                with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
                    response = client.request(method, url, **kwargs)
                    response.raise_for_status()
                    return response
            except Exception as exc:
                last_error = exc
                if attempt >= settings.llm_max_retries:
                    raise
                time.sleep(min(2**attempt, 4))
        raise RuntimeError(f"Unreachable retry state: {last_error}")

    def _parse_json_text(self, text: str) -> ReflectionArtifact:
        return _normalize_artifact(json.loads(text))

    def _parse_rewrite_json_text(self, text: str, original_query: str) -> QueryRewriteResult:
        return _normalize_rewrite_result(json.loads(text), original_query)


class OpenAIProvider(BaseHTTPProvider):
    name = "openai"

    def reflect(self, transcript: str) -> ReflectionArtifact:
        if not settings.openai_api_key:
            raise RuntimeError("MEMORYOS_OPENAI_API_KEY is not configured")
        response = self._request_with_retries(
            "POST",
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": settings.openai_model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": transcript},
                ],
            },
        )
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return self._parse_json_text(content)

    def rewrite_query(self, query: str, context: str) -> QueryRewriteResult:
        if not settings.openai_api_key:
            raise RuntimeError("MEMORYOS_OPENAI_API_KEY is not configured")
        response = self._request_with_retries(
            "POST",
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": settings.openai_model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": QUERY_REWRITE_PROMPT},
                    {"role": "user", "content": f"Query: {query}\n\nContext:\n{context}"},
                ],
            },
        )
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return self._parse_rewrite_json_text(content, query)


class GroqProvider(BaseHTTPProvider):
    name = "groq"

    def reflect(self, transcript: str) -> ReflectionArtifact:
        if not settings.groq_api_key:
            raise RuntimeError("MEMORYOS_GROQ_API_KEY is not configured")
        response = self._request_with_retries(
            "POST",
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json={
                "model": settings.groq_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": transcript},
                ],
                "response_format": {"type": "json_object"},
            },
        )
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return self._parse_json_text(content)

    def rewrite_query(self, query: str, context: str) -> QueryRewriteResult:
        if not settings.groq_api_key:
            raise RuntimeError("MEMORYOS_GROQ_API_KEY is not configured")
        response = self._request_with_retries(
            "POST",
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json={
                "model": settings.groq_model,
                "messages": [
                    {"role": "system", "content": QUERY_REWRITE_PROMPT},
                    {"role": "user", "content": f"Query: {query}\n\nContext:\n{context}"},
                ],
                "response_format": {"type": "json_object"},
            },
        )
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return self._parse_rewrite_json_text(content, query)


class AnthropicProvider(BaseHTTPProvider):
    name = "anthropic"

    def reflect(self, transcript: str) -> ReflectionArtifact:
        if not settings.anthropic_api_key:
            raise RuntimeError("MEMORYOS_ANTHROPIC_API_KEY is not configured")
        response = self._request_with_retries(
            "POST",
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": settings.anthropic_model,
                "max_tokens": 1200,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": transcript}],
            },
        )
        data = response.json()
        text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
        return self._parse_json_text(text)

    def rewrite_query(self, query: str, context: str) -> QueryRewriteResult:
        if not settings.anthropic_api_key:
            raise RuntimeError("MEMORYOS_ANTHROPIC_API_KEY is not configured")
        response = self._request_with_retries(
            "POST",
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": settings.anthropic_model,
                "max_tokens": 400,
                "system": QUERY_REWRITE_PROMPT,
                "messages": [{"role": "user", "content": f"Query: {query}\n\nContext:\n{context}"}],
            },
        )
        data = response.json()
        text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
        return self._parse_rewrite_json_text(text, query)


class GeminiProvider(BaseHTTPProvider):
    name = "gemini"

    def reflect(self, transcript: str) -> ReflectionArtifact:
        if not settings.gemini_api_key:
            raise RuntimeError("MEMORYOS_GEMINI_API_KEY is not configured")
        response = self._request_with_retries(
            "POST",
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent?key={settings.gemini_api_key}",
            json={
                "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"parts": [{"text": transcript}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            },
        )
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return self._parse_json_text(text)

    def rewrite_query(self, query: str, context: str) -> QueryRewriteResult:
        if not settings.gemini_api_key:
            raise RuntimeError("MEMORYOS_GEMINI_API_KEY is not configured")
        response = self._request_with_retries(
            "POST",
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent?key={settings.gemini_api_key}",
            json={
                "systemInstruction": {"parts": [{"text": QUERY_REWRITE_PROMPT}]},
                "contents": [{"parts": [{"text": f"Query: {query}\n\nContext:\n{context}"}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            },
        )
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return self._parse_rewrite_json_text(text, query)


provider_registry: dict[str, LLMProvider] = {
    "openai": OpenAIProvider(),
    "anthropic": AnthropicProvider(),
    "gemini": GeminiProvider(),
    "groq": GroqProvider(),
    "heuristic": HeuristicProvider(),
}


PROVIDER_ENV_FIELDS = {
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "gemini": "gemini_api_key",
    "groq": "groq_api_key",
}

PROVIDER_PRIORITY = ("groq", "openai", "anthropic", "gemini")


def provider_is_configured(name: str) -> bool:
    field_name = PROVIDER_ENV_FIELDS.get(name)
    if field_name is None:
        return name == "heuristic"
    return bool(getattr(settings, field_name, None))


def resolve_provider(preferred: str | None = None) -> LLMProvider:
    requested = (preferred or settings.default_provider or "auto").strip().lower()
    if requested in provider_registry and requested != "heuristic" and provider_is_configured(requested):
        return provider_registry[requested]
    if requested == "auto" or requested == "heuristic":
        for name in PROVIDER_PRIORITY:
            if provider_is_configured(name):
                return provider_registry[name]
        return provider_registry["heuristic"]
    if requested in provider_registry:
        for name in PROVIDER_PRIORITY:
            if provider_is_configured(name):
                return provider_registry[name]
        return provider_registry["heuristic"]
    return provider_registry["heuristic"]
