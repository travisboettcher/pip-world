# What Pip has made, shown on its own market stall: copies of a drawing stand framed, a creation Pip drew stands as its picture.
# Looks again every ten minutes, so the stall follows what Pip sets out and sells.
EVERY = 600


def _pictures(ctx):
    by_title = {w["title"].lower(): w for w in reversed(ctx["works"])}          # the newest drawing with a title wins
    by_subject = {w["subject"].lower(): w for w in reversed(ctx["works"]) if w["subject"]}
    show = []
    for line in ((ctx.get("facts") or {}).get("trade") or {}).get("stall") or []:          # what trade publishes
        copy = line["kind"] == "work" and line.get("work") == "drawing"
        w = by_title.get(line["item"].lower()) if copy else by_subject.get(line["item"].lower()) if line["kind"] == "creation" else None
        if not w:
            continue
        show.append({"id": f"stall-{len(show)}", "sprite": {"rows": w["rows"], "palette": w["palette"]}, "frame": copy,
                     "size": 0.6 if copy else 0.5, "at": {"type": "surface", "tags": ["stall", "pip"], "place": line["place"]},
                     "tip": {"title": line["item"], "text": f"{line['qty']} on Pip's stall." if copy else "On Pip's stall."}})
    return show[:8]


def on_install(ctx):
    return {"show": _pictures(ctx), "schedule": ctx["now"] + EVERY}


def on_time(ctx):
    return {"show": _pictures(ctx), "schedule": ctx["now"] + EVERY}
