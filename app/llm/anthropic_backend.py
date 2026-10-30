import base64

from anthropic import AsyncAnthropic

from ..config import Settings
from .base import LLMResponse, ToolCall, ToolSpec, Usage


def _to_api(m: dict) -> dict:
    if m["role"] == "assistant":
        if m.get("raw") is not None:
            return {"role": "assistant", "content": m["raw"]}  # replay blocks verbatim (incl. thinking)
        blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
        blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                   for c in m.get("tool_calls", [])]
        return {"role": "assistant", "content": blocks}
    if m["role"] == "tool":  # all results of one assistant turn go in a single user message
        return {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": r["id"], "content": _result_content(r),
             **({"is_error": True} if r.get("is_error") else {})}
            for r in m["results"]
        ]}
    return {"role": m["role"], "content": m["content"]}


def _result_content(r: dict):
    """A tool result is text, or text plus pictures (the model looks at them in this turn)."""
    if not r.get("images"):
        return r["content"]
    return [{"type": "text", "text": r["content"]}] + [
        {"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(data).decode()}}
        for mime, data in r["images"]]


class AnthropicBackend:
    name = "anthropic"

    def __init__(self, s: Settings):
        self.model = s.llm_model
        self.vision = s.llm_vision != "0"  # Claude models read images
        self.effort = s.llm_effort
        # Reads ANTHROPIC_API_KEY from the environment unless LLM_API_KEY is set.
        self.client = AsyncAnthropic(api_key=s.llm_api_key or None)

    async def complete(self, system, messages, tools: list[ToolSpec], max_tokens) -> LLMResponse:
        kwargs = {}
        if self.effort:
            kwargs["extra_body"] = {"output_config": {"effort": self.effort}}
        resp = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[_to_api(m) for m in messages],
            tools=[
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ],
            **kwargs,
        )
        text, calls = [], []
        for block in resp.content:
            if block.type == "text":
                text.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(block.id, block.name, dict(block.input)))
        return LLMResponse(
            text="".join(text).strip(),
            tool_calls=calls,
            usage=Usage(resp.usage.input_tokens, resp.usage.output_tokens),
            raw=resp.content,
        )
