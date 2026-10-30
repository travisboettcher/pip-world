"""Backend for any OpenAI-style /v1/chat/completions server (OpenAI, Ollama, vLLM, LM Studio)."""
import base64
import json

import httpx

from ..config import Settings
from .base import LLMResponse, ToolCall, ToolSpec, Usage


def _to_api(m: dict) -> list[dict]:
    if m["role"] == "assistant":
        out = {"role": "assistant", "content": m.get("content") or None}
        if m.get("tool_calls"):
            out["tool_calls"] = [
                {"id": c.id, "type": "function",
                 "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                for c in m["tool_calls"]
            ]
        return [out]
    if m["role"] == "tool":
        out = [{"role": "tool", "tool_call_id": r["id"], "content": r["content"]} for r in m["results"]]
        pictures = [(r["name"], mime, data) for r in m["results"] for mime, data in r.get("images", [])]
        if pictures:  # tool messages are text-only here, so the pictures follow as a user message
            out.append({"role": "user", "content": [{"type": "text", "text": "(the picture from the tool result above)"}] + [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}}
                for _, mime, data in pictures]})
        return out
    return [{"role": m["role"], "content": m["content"]}]


class OpenAICompatBackend:
    name = "openai_compat"
    vision = False  # set from LLM_VISION=1 in __init__ (depends on the model)

    def __init__(self, s: Settings):
        if not s.llm_base_url:
            raise ValueError("LLM_BASE_URL is required for the openai_compat backend")
        self.vision = s.llm_vision == "1"
        self.model = s.llm_model
        self.url = s.llm_base_url.rstrip("/") + "/chat/completions"
        self.headers = {"Authorization": f"Bearer {s.llm_api_key}"} if s.llm_api_key else {}
        self.http = httpx.AsyncClient(timeout=180)

    async def complete(self, system, messages, tools: list[ToolSpec], max_tokens) -> LLMResponse:
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, *[x for m in messages for x in _to_api(m)]],
            "tools": [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools
            ],
        }
        r = await self.http.post(self.url, json=body, headers=self.headers)
        r.raise_for_status()
        data = r.json()
        msg = data["choices"][0]["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            args = tc["function"].get("arguments") or "{}"
            try:
                parsed = json.loads(args) if isinstance(args, str) else args
            except json.JSONDecodeError:
                parsed = {}
            calls.append(ToolCall(tc.get("id", ""), tc["function"]["name"], parsed))
        u = data.get("usage") or {}
        return LLMResponse(
            text=(msg.get("content") or "").strip(),
            tool_calls=calls,
            usage=Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0)),
        )
