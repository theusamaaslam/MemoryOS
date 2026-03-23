from __future__ import annotations

import json
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


class LLMProvider(Protocol):
    name: str

    def reflect(self, transcript: str) -> ReflectionArtifact: ...


class HeuristicProvider:
    """Local fallback for offline development only."""

    name = "heuristic"

    def reflect(self, transcript: str) -> ReflectionArtifact:
        lines = [line.strip() for line in transcript.splitlines() if line.strip()]
        facts = [line for line in lines if "prefer" in line.lower() or "need" in line.lower()][:3]
        failures = [line for line in lines if "didn't" in line.lower() or "failed" in line.lower()][:2]
        preferences = [line for line in lines if "like" in line.lower() or "prefer" in line.lower()][:3]
        resolutions = [line for line in lines if "resolved" in line.lower() or "worked" in line.lower()][:2]
        retrieval_hints = [f"Prioritize on similar query: {line[:80]}" for line in facts[:2] + failures[:1]]
        return ReflectionArtifact(
            summary=lines[-1] if lines else "No transcript available",
            facts=facts or lines[:2],
            preferences=preferences,
            entities=[("User", "person"), ("Agent", "assistant")],
            relations=[("User", "Agent", "interacted_with")],
            failures=failures,
            resolutions=resolutions,
            retrieval_hints=retrieval_hints,
        )


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
- Never include markdown or code fences.
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


provider_registry: dict[str, LLMProvider] = {
    "openai": OpenAIProvider(),
    "anthropic": AnthropicProvider(),
    "gemini": GeminiProvider(),
    "groq": GroqProvider(),
    "heuristic": HeuristicProvider(),
}
