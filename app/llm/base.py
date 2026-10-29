"""Provider-neutral LLM interface. The loop only ever sees these types.

Messages are plain dicts, translated by each backend:
  {"role": "user", "content": str}
  {"role": "assistant", "content": str, "tool_calls": [ToolCall], "raw": <opaque>}
  {"role": "tool", "results": [{"id", "name", "content", "is_error"}]}
`raw` is whatever the backend returned in LLMResponse.raw; backends replay it
verbatim (e.g. Anthropic content blocks incl. thinking) when present.
"""
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON Schema object


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    raw: Any = None


class LLMBackend(Protocol):
    name: str

    async def complete(
        self, system: str, messages: list[dict], tools: list[ToolSpec], max_tokens: int
    ) -> LLMResponse: ...


def assistant_message(resp: LLMResponse) -> dict:
    return {"role": "assistant", "content": resp.text, "tool_calls": resp.tool_calls, "raw": resp.raw}
