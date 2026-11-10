# Pip's newest pixel drawings, framed and hung on the workshop's back wall: the newest a little bigger, the rest wherever the wall has room.
SHOWN = 3


def _hang(ctx):
    return {"show": [{"id": f"drawing-{w['id']}", "sprite": {"rows": w["rows"], "palette": w["palette"]}, "frame": True,
                      "size": 0.9 if i == 0 else 0.7, "at": {"type": "wall", "tags": ["inside", "back"], "place": "home"},
                      "tip": {"title": w["title"], "text": "One of Pip's drawings."}}
                     for i, w in enumerate(ctx["works"][:SHOWN])]}


def on_install(ctx):
    return _hang(ctx)


def on_event(ctx):
    return _hang(ctx)
