"""Capabilities: what Pip has actually been able to do, counted from outcomes (DESIGN-self.md, 6).

A measured record - tries and how they went per tool, craft and ability - so the self-portrait can draw on competence
that happened rather than on what Pip would like to be true (Voyager's verified skills; Lipson's self-model). Counts,
not judgments. Computed from the event log each night and kept as dated snapshots, so change over time is visible.
"""
from .toolnames import canonical

SKIP_TOOLS = {"set_activity", "say"}
GOOD_PHRASE = {"recall": "found something", "web_search": "found something", "browse": "found something", "gather": "found something"}
MIN_SHOWN = 3        # tries before an entry is shown
MAX_LINES = 8        # per group


def _tool_verdict(tool: str, result: str) -> str:
    if result.startswith(("error", "not ")):
        return "bad"
    if tool == "recall" and result.startswith("nothing comes to mind"):
        return "bad"
    return "good"


def collect(events, crafts: dict | None = None, stage_abilities: dict | None = None) -> dict:
    """{'tool': {name: {tries, good, neutral, bad}}, 'craft': {...}, 'ability': {...}} from events (any order).
    Older events didn't record the craft or abilities, so `crafts` {project_id: craft} and `stage_abilities`
    {(project_id, stage name): [abilities]} fill those in."""
    crafts, stage_abilities = crafts or {}, stage_abilities or {}
    out: dict = {"tool": {}, "craft": {}, "ability": {}}

    def hit(group, name, verdict):
        c = out[group].setdefault(name, {"tries": 0, "good": 0, "neutral": 0, "bad": 0})
        c["tries"] += 1
        c[verdict] += 1

    for e in events:
        k, d = e["kind"], e["data"]
        if k == "gathered" and not d.get("interrupted"):
            hit("tool", "gather", "good" if d.get("items") else "bad")
        elif k == "tool" and d.get("tool") not in SKIP_TOOLS and d.get("tool") != "gather" and not d.get("noop"):
            hit("tool", canonical(d["tool"]), _tool_verdict(canonical(d["tool"]), str(d.get("result", ""))))
        elif k == "work" and not d.get("interrupted") and d.get("result"):
            v = {"breakthrough": "good", "good": "good", "slow": "neutral"}.get(d["result"], "bad")
            for name in filter(None, [d.get("craft") or crafts.get(d.get("project_id"))]):
                hit("craft", name, v)
            for name in d.get("abilities") or stage_abilities.get((d.get("project_id"), d.get("stage"))) or []:
                hit("ability", name, v)
        elif k == "experiment" and not d.get("interrupted") and d.get("outcome"):
            v = {"insight": "good", "surprise": "good", "clue": "neutral"}.get(d["outcome"], "bad")
            if craft := d.get("craft") or crafts.get(d.get("project_id")):
                hit("craft", craft, v)
            for name in ("ingenuity", "knowledge"):
                hit("ability", name, v)
    return out


def _line(group: str, name: str, c: dict, before: dict | None) -> str:
    if group == "tool":
        good = GOOD_PHRASE.get(name, "worked")
        text = f"{name}: {c['tries']} tries, {c['good']} {good}" + (f", {c['bad']} didn't" if c["bad"] else "")
    else:
        noun = "sessions" if group != "ability" else "sessions and experiments"
        bits = [f"{c['good']} went well"] + ([f"{c['neutral']} slowly"] if c["neutral"] else []) + (
            [f"{c['bad']} badly"] if c["bad"] else [])
        text = f"{name}: {c['tries']} {noun}: " + ", ".join(bits)
    if before and before.get("tries", 0) < c["tries"]:
        text += f" (since last time: +{c['tries'] - before['tries']} tries, +{c['good'] - before['good']} good, " \
                f"+{c['bad'] - before['bad']} bad)"
    return text


def format_snapshot(now: dict, before: dict | None = None) -> str:
    """The prompt block: most-practised first, entries with at least MIN_SHOWN tries."""
    titles = {"tool": "Tools", "craft": "Crafts", "ability": "Abilities"}
    lines = []
    for group in ("tool", "craft", "ability"):
        rows = sorted(((n, c) for n, c in now[group].items() if c["tries"] >= MIN_SHOWN), key=lambda r: -r[1]["tries"])
        if rows:
            lines.append(f"{titles[group]}:")
            lines += [f"- {_line(group, n, c, (before or {}).get(group, {}).get(n))}" for n, c in rows[:MAX_LINES]]
    return "\n".join(lines)
