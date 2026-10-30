from .base import LLMResponse, ToolSpec


class FakeBackend:
    """Scripted responses for tests and zero-cost dry runs."""

    name = "fake"
    vision = True

    def __init__(self, script: list[LLMResponse] | None = None):
        self.script = list(script or [])
        self.calls: list[dict] = []

    def queue(self, *responses: LLMResponse) -> None:
        self.script.extend(responses)

    async def complete(self, system, messages, tools: list[ToolSpec], max_tokens) -> LLMResponse:
        self.calls.append({"system": system, "messages": messages, "tools": [t.name for t in tools]})
        return self.script.pop(0) if self.script else LLMResponse(text="...")
