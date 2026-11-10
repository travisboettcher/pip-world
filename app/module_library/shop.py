# A shop: a shopfront opened like a dollhouse, a counter with the keeper behind it while it's open, its stock on shelves or in a wall of
# drawers, and what its record mentions (rope, lanterns, boats at a harbour). Shut: the keeper gone home, a note on the door.
SX0, SX1, SZ0, SZ1 = -8.0, 4.0, -9.5, -3.6


def tex(name, rep=(1, 1), **kw):
    return {"texture": name, "repeat": list(rep), **kw}


def _box(size, at, mat, **kw):
    return {"shape": "box", "size": size, "at": at, "material": mat, **kw}


def on_build(ctx):
    d = ctx["details"]
    props = set(d.get("props") or [])
    harbour = "boats" in props and bool(d.get("coastal"))
    s = [{"shape": "box", "size": [32, 1, 16], "at": [0, -0.5, -4], "faces": {"top": tex("cobble", (16, 8)), "side": tex("stone", (16, 1))},
          "tip": {"title": "$label", "text": "$description"}}]
    if harbour:
        s += [_box([40, 0.6, 8], [0, -1.2, 8], tex("sea", (16, 4), rough=0.25, opacity=0.9), animate="flow", speed=0.01, shadow=False),
              {"shape": "box", "size": [40, 1.2, 0.6], "at": [0, -0.6, 4.1], "faces": {"top": tex("stone", (20, 1)), "side": tex("stone", (20, 1))}}]
        for i in range(2):
            x, z = -6 + i * 9, 6.5 + i * 1.2
            s += [_box([3.2, 0.7, 1.2], [x, -0.75, z], tex("planks", (3, 1), color=["#6b4a30", "#3f5a6a"][i]), rot=[0, round(5.73 - i * 11.46, 2), 0],
                       tip={"title": "A boat", "text": "Tied up at the harbour wall."}),
                  _box([0.1, 2.4, 0.1], [x, 0.6, z], tex("planks", (1, 2), color="#5a3d27"))]
    else:
        s.append({"shape": "box", "size": [40, 1, 10], "at": [0, -1.6, 9], "faces": {"top": tex("grass", (20, 5)), "side": tex("cliff", (20, 1))}})
    parts = [{"part": "cutaway", "params": {"width": SX1 - SX0, "depth": SZ1 - SZ0, "height": 3.4, "walls": d.get("walls") or ("stone" if harbour else "planks"),
                                            "roof": d.get("roof") or "shingle", "door": True}, "at": [(SX0 + SX1) / 2, 0, (SZ0 + SZ1) / 2], "role": "shop"}]
    # the counter, the stock behind it
    s += [_box([8.5, 1.0, 0.9], [-2.2, 0.5, -5.3], tex("planks", (4, 1), color="#7a5236")),
          _box([8.5, 1.0, 0.9], [-2.2, 0.5, -5.3], None, hitbox=True, tip={"title": "The counter", "text": "$stock"}),
          _box([10, 2.4, 0.5], [-2.2, 1.3, SZ0 + 0.5], tex("drawers", (6, 2)) if "drawers" in props else tex("planks", (3, 2), color="#6b4a30"))]
    s += [_box([10, 0.08, 0.6], [-2.2, y, SZ0 + 0.85], tex("planks", (4, 1), color="#5a3d27")) for y in (0.9, 1.7, 2.5)]
    if "rope" in props:
        s += [{"shape": "torus", "radius": 0.28, "tube": 0.09, "at": [round(-7.2 + i * 0.7, 2), 2.6, SZ0 + 1.0],
               "material": {"color": "#9a8a5a"}, "tip": {"title": "Coils of rope", "text": "Hung on pegs along the wall."}} for i in range(3)]
    if "lanterns" in props:
        for i in range(3):
            x = round(-5 + i * 2.6, 2)
            s += [_box([0.04, 0.8, 0.04], [x, 2.9, -6.6], tex("planks", color="#3f3326")), _box([0.34, 0.4, 0.34], [x, 2.4, -6.6], {"color": "#332211", "emissive": "#ffc070", "lamp": 0.9})]
    s += [{"shape": "light", "color": "#ffb066", "strength": 1, "range": 10, "at": [-2, 2.6, -6.5], "lamp": True},
          {"shape": "sprite", "art": "note", "size": [0.45, 0.45], "at": [SX1 + 0.62, 1.4, SZ0 + 2.1], "shadow": False, "when": "shut", "tip": {"title": "Shut", "text": "$hours"}}]
    anchors = [{"id": "counter", "type": "surface", "tags": ["inside", "counter", "reserved"], "at": [-2.2, 1.0, -5.3], "extent": [6.4, 0.6]},
               *({"id": f"stock-{k}", "type": "surface", "tags": ["inside", "stock", "reserved"], "at": [-2.2, y, SZ0 + 0.95], "extent": [9.0, 0.4]} for k, y in enumerate((0.95, 1.75, 2.55))),
               {"id": "pip", "type": "floor", "tags": ["inside", "pip", "reserved"], "at": [-1.2, 0.12, -4.3], "extent": [1, 1]},
               {"id": "people", "type": "floor", "tags": ["inside", "people", "reserved"], "at": [-1, 0.12, -4.2], "extent": [4, 1]},
               {"id": "back-wall", "type": "wall", "tags": ["inside", "back"], "at": [2.2, 2.2, SZ0 + 0.16], "normal": [0, 0, 1], "extent": [2.6, 1.0]},
               {"id": "outside", "type": "ground", "tags": ["outside"], "at": [-2, 0.0, -1.5], "extent": [8, 2]}]
    return {"parts": parts, "shapes": s, "anchors": anchors, "camera": {"at": [0, 13, 22], "look": [0, 0.4, -3]}}
