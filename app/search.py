"""Web search (see DESIGN-extract.md).

Where the answers come from is a *provider*: a small class registered by name (`@register("tavily")`) that turns a query into `Answers`.
This module is everything that does not care which: the answer type, how it is worded for Pip, the registry, and `run`. Pick the provider
with `SEARCH_PROVIDER`; add one by writing a module that registers a class with `ready` and `async fetch(query, http)`, then importing it
at the bottom. What comes back is untrusted text from the internet (Pip's guide says so); nothing here follows instructions found in it.
"""
from dataclasses import dataclass, field
from typing import Callable

MAX_CHARS = 1200      # what Pip reads of one search, at most
HIT_CHARS = 200       # of each result


@dataclass(frozen=True)
class Found:
    title: str
    text: str


@dataclass(frozen=True)
class Answers:
    summary: str = ""
    hits: list = field(default_factory=list)


PROVIDERS: dict[str, Callable] = {}     # name -> class(settings) with `ready` and `async fetch(query, http) -> Answers | None`


def register(name: str):
    def add(cls):
        PROVIDERS[name] = cls
        return cls
    return add


def provider(settings):
    """The configured provider, or None if the name is unknown."""
    cls = PROVIDERS.get(settings.search_provider)
    return cls(settings) if cls else None


def ready(settings) -> bool:
    source = provider(settings)
    return bool(source and source.ready)


def format(answers: Answers) -> str:
    """What Pip reads: the answer, then a line per result."""
    lines = [answers.summary] + [f"- {h.title}: {h.text[:HIT_CHARS]}" for h in answers.hits]
    return "\n".join(line for line in lines if line)[:MAX_CHARS]


async def run(settings, query: str, http=None) -> str | None:
    """Search and word the answer for Pip: '' if nothing came back, None if no provider is set up."""
    source = provider(settings)
    if not source or not source.ready:
        return None
    found = await source.fetch(query, http)
    return format(found) if found else ""


from . import search_tavily  # noqa: E402,F401  (registers the "tavily" provider)
