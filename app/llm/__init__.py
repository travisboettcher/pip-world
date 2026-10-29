from ..config import Settings
from .base import LLMBackend, LLMResponse, ToolCall, ToolSpec, Usage  # noqa: F401


def _anthropic(s: Settings):
    from .anthropic_backend import AnthropicBackend
    return AnthropicBackend(s)


def _openai_compat(s: Settings):
    from .openai_compat import OpenAICompatBackend
    return OpenAICompatBackend(s)


def _fake(s: Settings):
    from .fake import FakeBackend
    return FakeBackend()


# Add a backend: write a module implementing LLMBackend and register it here.
BACKENDS = {"anthropic": _anthropic, "openai_compat": _openai_compat, "fake": _fake}


def get_backend(s: Settings) -> LLMBackend:
    try:
        return BACKENDS[s.llm_backend](s)
    except KeyError:
        raise ValueError(f"unknown LLM_BACKEND {s.llm_backend!r}; options: {sorted(BACKENDS)}") from None
