# The library: a tall reading room opened like a dollhouse, walls of books, columns and steps at the front, a reading table under a lamp.
# Pip reads in a chair at the table, or browses along the shelves.
import random

LX0, LX1, LZ0, LZ1, LH = -9.0, 6.0, -10.0, -3.4, 4.4


def tex(name, rep=(1, 1), **kw):
    return {"texture": name, "repeat": list(rep), **kw}


def _box(size, at, mat, **kw):
    return {"shape": "box", "size": size, "at": at, "material": mat, **kw}


def on_build(ctx):
    d, r = ctx["details"], random.Random(ctx["seed"])
    s = [{"shape": "box", "size": [32, 1, 18], "at": [0, -0.5, -4], "faces": {"top": tex("cobble", (16, 9)), "side": tex("stone", (16, 1))}},
         {"shape": "box", "size": [40, 1, 10], "at": [0, -1.6, 9], "faces": {"top": tex("grass", (20, 5)), "side": tex("cliff", (20, 1))}}]
    parts = [{"part": "round-tree", "params": {"scale": 1.0}, "at": [10.5, 0, -6.5], "role": "tree-a"},
             {"part": "round-tree", "params": {"scale": 0.9}, "at": [-12, 0, -6], "role": "tree-b"},
             {"part": "cutaway", "params": {"width": LX1 - LX0, "depth": LZ1 - LZ0, "height": LH, "walls": d.get("walls") or "stone", "roof": d.get("roof") or "slate", "door": True},
              "at": [(LX0 + LX1) / 2, 0, (LZ0 + LZ1) / 2], "role": "library"}]
    parts += [{"part": "pine-tree", "params": {"scale": round(1.3 + r.random() * 0.7, 1)}, "at": [round(-16 + i * 2.8 + r.random(), 2), 0, round(-14 - r.random() * 2, 2)], "role": f"pine-{i}"}
              for i in range(12)]
    s.append(_box([LX1 - LX0, 0.2, LZ1 - LZ0], [(LX0 + LX1) / 2, 0.1, (LZ0 + LZ1) / 2], None, hitbox=True, tip={"title": "The library", "text": "$blurb"}))
    # columns and steps at the front
    s += [{"shape": "cylinder", "radius": 0.32, "top": 0.28, "height": LH, "segments": 10, "at": [x, LH / 2, LZ1 + 0.9], "material": tex("whitewash", (1, 3))}
          for x in (LX0 + 0.6, LX0 + 3, LX1 - 3, LX1 - 0.6)]
    s.append(_box([LX1 - LX0 + 1.4, 0.3, 1.6], [(LX0 + LX1) / 2, 0.15, LZ1 + 0.9], tex("stone", (8, 1))))
    # walls of books, a ladder, the reading table, chairs, the lamp
    s += [_box([LX1 - LX0 - 1, LH - 0.6, 0.6], [(LX0 + LX1) / 2, (LH - 0.6) / 2, LZ0 + 0.5], tex("books", (6, 3))),
          _box([0.6, LH - 0.6, 4.6], [LX0 + 0.5, (LH - 0.6) / 2, LZ0 + 3.2], tex("books", (3, 3))),
          _box([LX1 - LX0 - 1, LH - 0.6, 0.8], [(LX0 + LX1) / 2, (LH - 0.6) / 2, LZ0 + 0.6], None, hitbox=True,
               tip={"title": "The shelves", "text": "Real books: Pip can browse them, or settle in and read one."})]
    s += [_box([0.1, 3.4, 0.1], [x, 1.7, LZ0 + 1.0], tex("planks", (1, 2), color="#6b4a30"), rot=[-11.5, 0, 0]) for x in (2.4, 3.0)]
    wood = tex("planks", (2, 1), color="#7a5236")
    s += [_box([3.6, 0.14, 1.4], [-1.4, 0.9, -6.9], wood, tip={"title": "The reading table", "text": "A long table under a green-shaded lamp."})]
    s += [_box([0.14, 0.85, 0.14], [-1.4 + dx, 0.42, -6.9 + dz], wood) for dx in (-1.6, 1.6) for dz in (-0.55, 0.55)]
    s.append({"shape": "plane", "size": [0.7, 0.45], "at": [-0.6, 0.98, -6.6], "rot": [-90, 0, 0], "material": {"texture": "book"}})
    for x, z in ((-2.6, -5.6), (0.4, -5.6)):
        s += [_box([0.8, 0.5, 0.8], [x, 0.25, z], {"color": "#6a2f2a"}), _box([0.8, 0.8, 0.2], [x, 0.75, z + 0.35], {"color": "#6a2f2a"})]
    s += [_box([0.06, 0.5, 0.06], [-1.4, 1.2, -7.2], {"color": "#3a3a2a"}),
          _box([0.6, 0.25, 0.4], [-1.4, 1.5, -7.2], {"color": "#2a4a2a", "emissive": "#ffd080", "lamp": 0.9}),
          {"shape": "light", "color": "#ffc070", "strength": 0.9, "range": 8, "at": [-1.4, 2.2, -6.6], "lamp": True},
          {"shape": "plane", "size": [1.0, 1.4], "at": [LX1 - 1.4, 3.3, LZ0 + 0.21], "material": {"texture": "window", "emissive": "#ffb050", "lamp": 0.6}}]
    anchors = [{"id": "reading", "type": "floor", "tags": ["inside", "reading", "reserved"], "at": [-2.6, 0.51, -5.5], "extent": [0.8, 0.8]},
               {"id": "browse", "type": "floor", "tags": ["inside", "browse", "reserved"], "at": [-2.0, 0.12, LZ0 + 1.6], "extent": [6.0, 0.6]},
               {"id": "pip", "type": "floor", "tags": ["inside", "pip", "reserved"], "at": [-2.0, 0.12, LZ0 + 1.6], "extent": [6.0, 0.6]},
               {"id": "table", "type": "surface", "tags": ["inside", "table"], "at": [-2.2, 0.97, -6.9], "extent": [1.8, 1.2]},
               {"id": "people", "type": "floor", "tags": ["inside", "people", "reserved"], "at": [-4, 0.12, -5], "extent": [4, 1]},
               {"id": "steps", "type": "ground", "tags": ["outside"], "at": [(LX0 + LX1) / 2, 0.3, LZ1 + 0.9], "extent": [12, 1.2]}]
    return {"parts": parts, "shapes": s, "anchors": anchors, "camera": {"at": [0, 13, 21], "look": [0, 0.6, -4.2]}}
