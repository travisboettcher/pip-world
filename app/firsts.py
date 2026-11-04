"""Firsts: the first time something happens to Pip, computed from the event log (see DESIGN-self.md).

Each logged event yields a few independent *facets* (a stable key plus a plain-fact label). A facet seen for the
first time is a "first": it is stored in the `facets` table, marked on the event, and shown to Pip as a fact. The
engine never says what a first means - no mood words, no scripted reactions. Pip decides if it matters.
Add a new kind of first by extending `facets()`.
"""
from . import sleep as sleepmod
from .toolnames import canonical

MAJOR, MINOR = "major", "minor"
ROUTINE_TOOLS = {"set_activity", "say", "edit_note"}
TOOL_LABELS = {
    "plant": "planted something", "harvest": "harvested something", "eat": "ate something",
    "start_project": "started a project", "work_on": "worked on a project", "experiment": "ran an experiment",
    "revise_plan": "changed a plan", "write_letter": "wrote a letter", "read": "read a book",
    "browse": "browsed what was on offer", "web_search": "searched the web", "recall": "tried to remember something",
    "tend": "tended to something", "use_item": "used something", "rest": "rested", "resolve_note": "crossed something off",
    "sleep": "went to sleep", "abandon_project": "gave up on a project",
}
TOOL_MAJOR = {"sleep"}
WORK_RESULTS = {"setback": "had a setback on a project", "blowup": "had a try blow up",
                "breakthrough": "had a breakthrough"}
HAPPENING_FIRSTS = {
    "garden": "had the garden change on its own", "creature": "had a small creature come by", "pantry": "found some of your food had turned",
    "found": "came across something unexpected", "body": "woke up feeling different", "market": "heard talk of the market",
    "mishap": "had something go wrong in the workshop", "neighbor": "heard news of a neighbor", "memory": "had an old thought come back",
    "kindness": "was given something by someone unseen", "atmosphere": "noticed something in the air"}
ALERTS = {"hunger": "your hunger alert went off", "energy": "your energy alert went off"}


def _ok(result) -> bool:
    return not str(result or "").startswith(("error", "not ", "no change"))


def _surprise(add, d: dict) -> None:
    if d.get("surprise") in ("better", "worse"):
        add(f"surprise:{d['surprise']}", f"the first time something went much {d['surprise']} than you expected", MAJOR)


def facets(kind: str, d: dict, settings, ts: float) -> list[tuple[str, str, str]]:
    """(key, label, tier) for each facet of this event. Labels read as 'the first time you <label>'."""
    out: list[tuple[str, str, str]] = []

    def add(key, label, tier=MINOR):
        out.append((key, label, tier))

    def you(what):  # "the first time you <what>"
        return f"the first time you {what}"

    if kind == "tool":
        t, a = canonical(d.get("tool")), d.get("args") or {}
        if not d.get("noop") and _ok(d.get("result")):
            if t == "note_to_self":
                sec = a.get("section", "diary")
                add(f"note:{sec}", f"your first {sec} entry")
            elif t in TOOL_LABELS and t not in ROUTINE_TOOLS:
                add(f"tool:{t}", you(TOOL_LABELS[t]), MAJOR if t in TOOL_MAJOR else MINOR)
    elif kind == "outreach":
        if d.get("what") == "postcard" and d.get("delivered"):
            add("outreach:postcard", you("sent something out into the world"), MAJOR)
        elif d.get("what") == "reply" and d.get("delivered"):
            add("outreach:reply", you("answered someone outside"))
    elif kind == "inbox":
        who = d.get("sender") or "A visitor"
        if d.get("source") not in (None, "web"):
            add(f"heard:{d['source']}", you(f"heard from someone outside, through {d['source']}"), MAJOR)
        if d.get("letter"):
            add("letter:received", you("received a letter"), MAJOR)
            add(f"letter_from:{who}", f"your first letter from {who}")
        elif not d.get("gift"):
            add("visitor", "the first time someone came to talk to you", MAJOR)
            if who != "A visitor":  # the default name for an anonymous caller is not a person
                add(f"person:{who}", f"your first message from {who}", MAJOR)
    elif kind == "gift":
        add("gift", you("were given something"), MAJOR)
        if d.get("sender"):
            add(f"gift_from:{d['sender']}", f"your first gift from {d['sender']}")
        if d.get("item"):
            add(f"gift_item:{str(d['item']).lower()}", you(f"were given {d['item']}"))
    elif kind == "letter_sent":
        add("letter:sent", you("sent a letter"), MAJOR)
    elif kind == "work":
        if not d.get("interrupted"):
            if d.get("result") in WORK_RESULTS:
                add(f"work:{d['result']}", you(WORK_RESULTS[d["result"]]), MAJOR)
            if d.get("project_done"):
                add("project:done", you("finished a project"), MAJOR)
            _surprise(add, d)
    elif kind == "experiment":
        if not d.get("interrupted"):
            _surprise(add, d)
        if not d.get("interrupted") and d.get("outcome") in ("insight", "surprise"):
            add(f"experiment:{d['outcome']}", you(f"had an experiment give you {'an insight' if d['outcome'] == 'insight' else 'a surprise'}"))
    elif kind == "gathered":
        for it in d.get("items", []):
            add(f"found:{it['name']}", you(f"found {it['name']}"))
    elif kind == "creation_made":
        add("creation", you("finished making a thing"), MAJOR)
    elif kind == "reading":
        if d.get("finished"):
            add("book_finished", you("finished a book"))
    elif kind == "arrived":
        if d.get("place") and d["place"] != "workshop":  # getting home is never new
            add(f"place:{d['place']}", you(f"were at {d['place']}"))
    elif kind == "revised_work":
        add("work:revised", you("looked at your own picture and redid it"), MAJOR)
    elif kind == "made_work":
        add(f"work_made:{d.get('what')}", you("finished a drawing" if d.get("what") == "drawing" else "finished a piece of writing to share"), MAJOR)
    elif kind == "world_changed":
        add(f"world:{d.get('effect')}", you("changed the world around you"), MAJOR)
    elif kind == "stall_sale":
        add("stall:sale", you("sold something at your own stall"), MAJOR)
    elif kind == "happening":
        if d.get("category") in HAPPENING_FIRSTS and d.get("status") == "applied":
            add(f"happening:{d['category']}", you(HAPPENING_FIRSTS[d["category"]]))
    elif kind == "happening_felt":
        if d.get("differs") and d.get("read_as") != "nothing":
            add("happening:read_differently", you("took something that happened differently from how it was told"), MAJOR)
    elif kind == "night_pass":
        if d.get("applied"):
            add("night_pass", you("changed your plans in your sleep"), MAJOR)
    elif kind == "woke":
        add("woke", you("woke from sleep"), MAJOR)
    elif kind == "reflection":
        add("reflection", you("went over your day in your sleep"), MAJOR)
    elif kind == "alert":
        if d.get("stat") in ALERTS:
            add(f"alert:{d['stat']}", f"the first time {ALERTS[d['stat']]}", MAJOR)
    elif kind == "companion":
        if d.get("name"):
            add(f"companion:{d['name']}", you(f"heard {d['name']} speak"))
    elif kind == "garden":
        add("garden:ripe", you("had a crop ripen"))
    elif kind == "tick":
        p = sleepmod.period(settings, ts)
        add(f"period:{p}", f"your first {p} here")
    return out
