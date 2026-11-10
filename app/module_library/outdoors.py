# Every place out of doors without a layout of its own: wild places to forage, yards to dig through, spots just to see. The land follows
# the place's setting (wood, shore, marsh, hills, heath, riverside, field, town); a yard has heaps of scrap, a shed and a fence; a sight
# has something to look at and a bench to look from; a lighthouse stands where people speak of one. Pip, finds and people have anchors.
import random

GROUND = {"heath": "heather", "shore": "sand", "marsh": "marsh", "town": "cobble"}


def _trees(r, round_, pines=()):
    out = [{"part": "round-tree", "params": {"scale": s}, "at": [x, y, z], "role": f"tree-{i}"} for i, (x, z, s, y) in enumerate(round_)]
    out += [{"part": "pine-tree", "params": {"scale": s}, "at": [x, 0, z], "role": f"pine-{i}"} for i, (x, z, s) in enumerate(pines)]
    return out


def on_build(ctx):
    d = ctx["details"]
    kind, setting, props = d.get("kind"), d.get("setting") or ("hills" if d.get("kind") == "yard" else "wood"), set(d.get("props") or [])
    r = random.Random(ctx["seed"])
    rnd = lambda a, b: round(a + r.random() * (b - a), 2)
    land = {"texture": GROUND.get(setting, "grass"), "repeat": [15, 8]}
    shapes = [{"shape": "box", "size": [30, 2, 16], "at": [0, -1, -4], "faces": {"top": land, "side": {"texture": "cliff", "repeat": [15, 1]}},
               "tip": {"title": "$label", "text": "$description"}},
              {"shape": "box", "size": [40, 1, 12], "at": [0, -2.5, 9], "faces": {"top": {"texture": "sand" if setting == "shore" else "grass", "repeat": [20, 6]},
                                                                                  "side": {"texture": "cliff", "repeat": [20, 1]}}}]
    parts = []
    if setting == "wood":
        round_ = [(rnd(-13, 13), rnd(-11, -6), round(rnd(0.8, 1.4), 1), 0) for _ in range(9)] + [(-11, 1.5, 1.0, 0), (11.5, 0.5, 1.1, 0)]
        parts += _trees(r, round_, [(rnd(-14, 14), rnd(-15.5, -12.5), round(rnd(1.1, 1.9), 1)) for _ in range(18)])
    elif setting in ("shore", "marsh"):
        shapes.append({"shape": "box", "size": [40, 1, 12], "at": [0, -1.1, -16], "material": {"texture": "sea", "repeat": [16, 8], "rough": 0.25, "opacity": 0.9},
                       "animate": "tide", "speed": 0.01, "shadow": False})
        shapes += [{"shape": "dodeca", "radius": rnd(0.4, 0.9), "at": [rnd(-12, 12), 0.2, rnd(-12, -10)], "material": {"texture": "stone"}} for _ in range(8)]
        if setting == "marsh":
            shapes += [{"shape": "sprite", "art": "reed", "size": [0.5, 1.0], "at": [rnd(-13, 13), 0.45, rnd(-9, 3)], "shadow": False} for _ in range(50)]
    elif setting in ("hills", "heath"):
        hill = {"texture": "heather", "repeat": [3, 3]} if setting == "heath" else {"texture": "grass", "repeat": [3, 3]}
        shapes += [{"shape": "sphere", "radius": rnd(4, 6), "segments": 8, "at": [round(-14 + i * 7 + r.random() * 2, 2), -0.2, rnd(-15, -13)],
                    "scale": [1, 0.45, 1], "material": hill} for i in range(5)]
        shapes += [{"shape": "dodeca", "radius": rnd(0.35, 0.75), "at": [rnd(-12, 12), 0.25, rnd(-8, 2)], "material": {"texture": "stone"}} for _ in range(7)]
    elif setting == "riverside":
        shapes.append({"shape": "box", "size": [40, 0.3, 2.4], "at": [0, 0.02, -6], "material": {"texture": "water", "repeat": [14, 2], "rough": 0.3},
                       "animate": "flow", "speed": 0.03})
        shapes.append({"shape": "box", "size": [2.2, 0.3, 3.4], "at": [3, 0.3, -6], "material": {"texture": "planks", "repeat": [1, 4], "color": "#8a6440"}})
        parts += _trees(r, [(-9, -10, 1.1, 0), (8, -10.5, 1.0, 0), (12, 1, 0.9, 0)])
    else:
        parts += _trees(r, [(-11, -9, 1.0, 0), (11, -8.5, 1.1, 0)])
    if "lighthouse" in props:
        parts.append({"part": "lighthouse", "at": [-10, 0, -12], "role": "lighthouse"})
    if kind == "yard":
        parts += [{"part": "scrap-heap", "at": [round(-9 + h * 5.5 + r.random(), 2), 0, rnd(-9, -6)], "role": f"heap-{h}"} for h in range(4)]
        parts.append({"part": "shed", "at": [9.5, 0, -9.5], "role": "shed"})
        shapes += [{"shape": "box", "size": [0.12, 1.0, 0.12], "at": [x, 0.5, -12.6], "material": {"texture": "planks", "repeat": [1, 1], "color": "#5a4a3a"}}
                   for x in [round(-13 + i * 1.3, 2) for i in range(21)]]
    if kind == "sight":
        parts.append({"part": "bench", "at": [0, 0, 1.4], "role": "bench"})
        if "lighthouse" not in props:
            parts.append({"part": "standing-stones", "at": [0, 0, -8.2], "role": "stones"})
    anchors = [{"id": "pip", "type": "ground", "tags": ["outside", "pip", "people"], "at": [-1.5, 0, 0.5], "extent": [10, 3]},
               {"id": "finds", "type": "ground", "tags": ["outside", "finds"], "at": [-1, 0, -2.5], "extent": [18, 6]},
               {"id": "open-ground", "type": "ground", "tags": ["outside", "clearing"], "at": [0, 0, -3], "extent": [12, 3]}]
    return {"parts": parts, "shapes": shapes, "anchors": anchors}
