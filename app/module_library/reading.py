# Reading (docs/DESIGN-world-packs.md, phase 5d): the library's `browse` and `read`, on the engine's `books` source (the owner's books:
# finding them, and a stretch of one condensed by the GM; sources.py). A reading session takes real time; when it ends the source reads
# on from the bookmark, which this module keeps (where it is in each book, how far, whether it's done), and the moment is told.
READ_MINUTES = (15, 90)
DEFAULT_MINUTES = 45
SHOWN = 5                       # books partway through, shown at the library
PUBLISHED = 30                  # bookmarks published for the dashboard
LIBRARY = "library"


def clip(text, limit):
    """The engine's clip: whitespace collapsed, cut at a sentence end when there is one."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("* "))
    return cut[:end + 1] if end > limit // 3 else cut.rsplit(" ", 1)[0] + "..."


def clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def marks(ctx):
    return ctx["store"].get("marks", {})


def mark_of(ctx, book_id):
    return marks(ctx).get(str(book_id))


def line(ctx, b):
    m = mark_of(ctx, b["id"])
    status = ("can't be read" if not b["readable"] else "finished" if m and m["finished"] else
              "you're " + str(m["percent"]) + "% in" if m and m["sessions"] else "")
    return ("#" + str(b["id"]) + " " + b["title"] + " - " + b["authors"] + (" [" + b["tags"] + "]" if b["tags"] else "")
            + (" (" + status + ")" if status else "") + (": " + clip(b["description"], 140) if b["description"] else ""))


def view(ctx, store=None):
    """What every call leaves: the books partway through (shown at the library), and the bookmarks published for the dashboard."""
    all_marks = dict(marks(ctx))
    for k, v in ((store or {}).get("marks") or {}).items():
        all_marks[k] = v
    recent = sorted((m for m in all_marks.values() if m), key=lambda m: -(m.get("last_read") or 0))
    reading = [m for m in recent if not m["finished"] and not m["unreadable"]][:SHOWN]
    here = ctx.get("here")
    out = {"publish": {"bookmarks": recent[:PUBLISHED]}}
    if here and here["key"] == LIBRARY and reading:
        out["status"] = {"title": "Books you're partway through", "lines": ["#" + str(m["book_id"]) + " " + m["title"] + " (" + str(m["percent"]) + "% in)"
                                                                            for m in reading]}
    else:
        out["status"] = {}
    if store:
        out["store"] = store
    return out


def bookmark(ctx, b, **fields):
    m = dict(mark_of(ctx, b["id"]) or {"book_id": b["id"], "title": b["title"], "section": 0, "offset": 0, "percent": 0, "sessions": 0,
                                        "finished": False, "unreadable": False, "last_read": None})
    m.update(fields)
    return {"marks": {str(b["id"]): m}}


# --- the tools ------------------------------------------------------------------------------------------------------------------------
def on_install(ctx):
    return view(ctx)


def on_action(ctx):
    args = ctx["args"]
    if ctx["tool"] == "browse":
        q = str(args.get("query") or "").strip()
        return {"source": {"name": "books", "op": "search", "args": {"query": q}} if q else {"name": "books", "op": "wander"}}
    return {"source": {"name": "books", "op": "find", "args": {"book": str(args.get("book") or "")}}}


def on_source(ctx):
    got, ask = ctx["source"]["answer"], ctx["source"]
    if "error" in got and got["error"] and ask["op"] != "find":
        return {"reply": "error: " + got["error"]}
    if ask["op"] == "search":
        q = ask["args"]["query"]
        if not got["books"]:
            return {"reply": "nothing on the shelves matches " + repr(q)}
        return {"reply": "Looking for " + repr(q) + ", you find:\n" + "\n".join("- " + line(ctx, b) for b in got["books"])}
    if ask["op"] == "wander":
        if not got["books"]:
            return {"reply": "the shelves here are empty"}
        return {"reply": "Wandering along " + got["shelf"] + ", you see:\n" + "\n".join("- " + line(ctx, b) for b in got["books"])}
    if ask["op"] == "find":
        return start(ctx, got)
    return finish(ctx, got)


def start(ctx, got):
    b = got.get("book")
    if not b:
        return {"reply": "error: " + (got.get("error") or "there's no such book here")}
    if not b["readable"]:
        return {"reply": b["title"] + " is bound in a way you can't open (" + ", ".join(b["formats"]) + ")"}
    m = mark_of(ctx, b["id"])
    if m and m["finished"]:
        return {"reply": "you've already finished " + b["title"]}
    if m and m["unreadable"]:
        return {"reply": b["title"] + " is almost all pictures; there's nothing more to read"}
    minutes = clamp(ctx["args"].get("minutes"), READ_MINUTES[0], READ_MINUTES[1], DEFAULT_MINUTES)
    where = "picking up where you left off, " + str(m["percent"]) + "% in" if m and m["sessions"] else "from the start"
    store = bookmark(ctx, b)
    store["now"] = {"session": {"id": b["id"], "title": b["title"], "minutes": minutes}}
    out = view(ctx, store)
    out.update(session={"minutes": max(1, round(minutes / ctx["params"]["speed"])), "label": "reading " + b["title"]},
               doing={"activity": "reading", "description": "reading " + b["title"]},
               reply="you settle in with " + b["title"] + " by " + b["authors"] + " (" + where + ") for " + str(minutes) + " min")
    return out


# --- the session's end: the source reads on, and the moment is told ---------------------------------------------------------------------
def on_time(ctx):
    s, now = ctx.get("session"), ctx["store"].get("now", {}).get("session")
    if not s or not now:
        return view(ctx)
    minutes = now["minutes"]
    if s["interrupted"]:
        minutes = min(minutes, s["minutes"] * ctx["params"]["speed"])
    out = {"practice": {"knowledge": min(240, minutes)}} if minutes > 0 else {}
    m = mark_of(ctx, now["id"]) or {"section": 0, "offset": 0}
    out["source"] = {"name": "books", "op": "read", "args": {"id": now["id"], "section": m["section"], "offset": m["offset"], "minutes": minutes}}
    out["store"] = {"now": {"session": {**now, "read": minutes, "interrupted": s["interrupted"]}}}
    return out


def finish(ctx, got):
    now = ctx["store"]["now"]["session"]
    b = {"id": now["id"], "title": now["title"]}
    m = mark_of(ctx, now["id"]) or {"sessions": 0}
    t = ctx["now"]
    finished = False
    if got.get("failed"):
        summary, quotes, percent, store = "The pages wouldn't come apart properly; you couldn't make sense of this one.", [], m.get("percent", 0), {}
    elif got.get("pictures"):
        summary, quotes, percent = "These pages are almost all pictures; there's hardly any text to read here.", [], m.get("percent", 0)
        store = bookmark(ctx, b, unreadable=True, last_read=t, sessions=m["sessions"] + 1)
    elif got.get("summary"):
        summary, quotes, percent, finished = got["summary"], got["quotes"][:2], got["percent"], got["done"]
        store = bookmark(ctx, b, section=got["section"], offset=got["offset"], percent=got["percent"], finished=got["done"],
                         sessions=m["sessions"] + 1, last_read=t)
    else:
        summary, quotes, percent, store = "You'd barely started before you put it down.", [], m.get("percent", 0), {}
    store["now"] = {"session": None}
    out = view(ctx, store)
    text = ("You read " + now["title"] + (" (and finished it)" if finished else " (now " + str(percent) + "% through)") + ": " + summary
            + "".join(' "' + q + '"' for q in quotes))
    out["log"] = {"text": clip(text, 1200), "kind": "finished_book" if finished else "read", "tool": "read"}
    if ctx["agent"]["activity"] == "reading":
        out["doing"] = {"activity": "idle", "description": "just read some of " + now["title"]}
    out["wake"] = True
    return out
