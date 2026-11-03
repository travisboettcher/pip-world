"""The guide: how this world works, told to the agent at every wake (see DESIGN-extract.md, "Persona: ship a world manual, not a character").

The guide is engine-owned: one text file per topic in this folder, put together from only what is enabled, so the agent is never told about something it
cannot do and a smaller setup costs fewer tokens. It is a manual in a neutral voice; it never says who the agent is, how it feels or how it should behave
towards people. That is the *persona*: an optional file the deployment supplies (`PERSONA_PATH`), put in front of the guide.

To add a topic: write `<name>.md` here and one `Section` below saying when it applies.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

DIR = Path(__file__).parent


@dataclass(frozen=True)
class Section:
    name: str
    needs: Callable    # (tools: set[str], settings, library: bool) -> bool
    bullet: bool = False   # a line of the closing "Guidelines" list rather than a paragraph


def tool(*names: str) -> Callable:
    return lambda tools, s, lib: any(n in tools for n in names)


always = lambda tools, s, lib: True  # noqa: E731

# In the order the agent reads them. A topic that mentions a tool is told only when that tool is enabled.
SECTIONS = (
    Section("world", always),
    Section("visitors", tool("say")),
    Section("journal", tool("note_to_self", "edit_note", "resolve_note")),
    Section("belongings", tool("plant", "use_item")),
    Section("market", tool("buy", "sell", "pay")),   # right after belongings; the old manual is one run from "projects" to the guidelines
    Section("projects", tool("start_project")),
    Section("creations", tool("start_project")),
    Section("memory", lambda tools, s, lib: s.reflect_hour < 24),
    Section("recall", tool("recall")),
    Section("neighbor", lambda tools, s, lib: "write_letter" in tools and s.neighbor),
    Section("home", tool("go_to")),
    Section("library", lambda tools, s, lib: lib and any(n in tools for n in ("browse", "read"))),
    Section("places", tool("gather", "where_to")),
    Section("outreach", tool("send_postcard")),
    Section("building", tool("start_project")),
    Section("art", tool("draw", "write_piece")),
    Section("emotions", lambda tools, s, lib: s.emotions == "on"),
    Section("settle", lambda tools, s, lib: s.emotions == "on" and "settle" in tools),
    Section("sleep", lambda tools, s, lib: "sleep" in tools and s.sleep),
    Section("nightpass", lambda tools, s, lib: s.night_pass != "off"),
    Section("care", tool("eat", "rest"), bullet=True),
    Section("activity", tool("set_activity"), bullet=True),
    Section("answering", tool("say"), bullet=True),
    Section("search", tool("web_search"), bullet=True),
    Section("brevity", always, bullet=True),
    Section("handover", lambda tools, s, lib: "write_letter" in tools and s.neighbor, bullet=True),
)


def render(tools, settings, library: bool) -> str:
    """The manual for what is enabled: paragraphs, then the Guidelines list."""
    tools = set(tools)
    paragraphs, bullets = [], []
    for section in SECTIONS:
        if section.needs(tools, settings, library):
            (bullets if section.bullet else paragraphs).append((DIR / f"{section.name}.md").read_text().strip("\n"))
    return "\n\n".join(paragraphs + (["Guidelines:\n" + "\n".join(bullets)] if bullets else []))
