"""The public, read-only view (docs/DESIGN-public-view.md).

A request whose Host is one of PUBLIC_HOSTS is public. Public requests are default-deny: only the GET paths below answer, every
response is scrubbed here, and nothing a viewer does calls the model, wakes Pip or writes. Anything not listed is a 404, so a new
endpoint is owner-only until someone classifies it.
"""
import re

MAX_PUBLIC_STREAMS = 50
CACHE_SECONDS = 5

PUBLIC_PATHS = frozenset({
    "/", "/mode", "/healthz", "/state", "/events", "/stream", "/notes", "/items", "/emotions", "/garden", "/projects",
    "/creations", "/works", "/map", "/places", "/memory", "/happenings",
})
PUBLIC_PATTERNS = (re.compile(r"/ui(/.*)?"), re.compile(r"/works/\d+(\.svg|\.png)?"))

# Only these event kinds are public, and only these fields of each. Anything unlisted (say, inbox, gift, letters, outreach,
# companion, errors, start...) is dropped. `firsts` and `returns` are facts the engine computes about an event.
EVENT_FIELDS = {
    "tick": ("step", "text", "tools"),
    "garden": ("plot", "crop"),
    "woke": ("hours", "early"),
    "emotion": ("emotion", "value", "cause"),
    "settled": ("emotion", "from", "to", "how"),
    "arrived": ("place", "label", "first_time", "description"),
    "reading": ("title", "minutes", "summary", "quotes", "percent", "finished"),
    "work": ("project", "stage", "result", "minutes", "text", "finished_stage", "project_done", "percent"),
    "experiment": ("project", "hypothesis", "outcome", "minutes", "text", "finding", "project_done", "percent"),
    "gathered": ("place", "label", "minutes", "items", "text"),
    "creation": ("name", "what", "text", "item"),
    "creation_made": ("name", "description", "quality", "capabilities", "quirks", "project"),
    "made_work": ("id", "what", "title", "caption", "text"),
    "revised_work": ("id", "title", "revision"),
    "world_changed": ("effect", "text", "name"),
    "plan_revised": ("project", "because"),
    "reflection": ("summary", "insights", "changes", "turning"),
    "night_pass": ("decisions", "focus", "kept", "carried", "dropped", "applied"),
    "heard_of_place": ("place", "distance"),
    "resident": ("name", "place", "about"),
    "neighbor": ("name", "about"),
    "alert": ("stat",),
    "wished": ("id", "wish", "text"),
    "stall_sale": ("place", "item", "qty", "coins", "left"),
    "happening": ("id", "category", "severity", "lens", "title", "text", "effects"),
    "happening_felt": ("id", "title", "lens", "read_as"),
}
ALWAYS = ("firsts", "returns")

# A tool's result is shown only for these; any other tool (say, letters, postcards, recall) shows just its name.
TOOLS_WITH_RESULT = frozenset({
    "set_activity", "eat", "rest", "use_item", "plant", "harvest", "start_project", "work_on", "abandon_project", "tend",
    "go_to", "browse", "read", "gather", "where_to", "experiment", "revise_plan", "sleep", "resume_project", "draw",
    "write_piece", "look", "settle", "note_to_self", "edit_note", "resolve_note", "web_search", "buy", "sell", "pay", "feel",
})

GENERIC_NAMES = frozenset({"a visitor", "visitor", "someone", "anonymous", "guest"})


def host_of(request) -> str:
    return request.headers.get("host", "").split(":")[0].lower()


def is_public(request, settings) -> bool:
    return host_of(request) in settings.public_hosts


def allowed(method: str, path: str) -> bool:
    return method in ("GET", "HEAD") and (path in PUBLIC_PATHS or any(p.fullmatch(path) for p in PUBLIC_PATTERNS))


def names_to_hide(state, settings) -> list[str]:
    """Everyone who has written to Pip or that Pip keeps notes on, plus PUBLIC_REDACT, longest first (so "Ann Lee" beats "Ann")."""
    names = {*settings.public_redact, *state.senders(), *(p["name"] for p in state.people())}
    return sorted((n for n in names if len(n.strip()) >= 3 and n.strip().lower() not in GENERIC_NAMES), key=len, reverse=True)


def redact(value, names: list[str]):
    """Replace each name, as a whole word and in any case, with "someone" in every string of a JSON-like value."""
    if not names:
        return value
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(n.strip()) for n in names) + r")(?!\w)", re.I)

    def walk(v):
        if isinstance(v, str):
            return pattern.sub("someone", v)
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        return v
    return walk(value)


def public_event(event: dict) -> dict | None:
    kind = event["kind"]
    data = event["data"]
    if kind == "tool":
        keep = {"tool": data.get("tool")}
        if data.get("tool") in TOOLS_WITH_RESULT and "result" in data:
            keep["result"] = data["result"]
    elif kind in EVENT_FIELDS:
        keep = {k: data[k] for k in (*EVENT_FIELDS[kind], *ALWAYS) if k in data}
    else:
        return None
    return {"id": event["id"], "ts": event["ts"], "kind": kind, "importance": event.get("importance"), "data": keep}


def public_events(state, settings):
    """A function for the event stream and /events: drops private events, trims the rest, hides names."""
    names = names_to_hide(state, settings)

    def transform(event: dict) -> dict | None:
        out = public_event(event)
        return redact(out, names) if out else None
    return transform


def public_state(state_json: dict) -> dict:
    return {"agent": state_json["agent"], "ticks": state_json["ticks"], "coins": state_json["coins"]}
