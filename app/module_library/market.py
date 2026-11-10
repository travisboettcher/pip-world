# A market square: cobbles, houses round it lit at night, pines on the hill behind, a well, bunting, lamp posts, and stalls. Each booth the
# engine has for today stands at a stall in turn (its keeper behind it while the market is open); Pip's own stall stands at the front, its
# awning out while Pip has something set out. People walk about the square while it's open.
import math
import random

SLOTS = [[-9.5, -8.2], [-4.4, -9.0], [4.6, -9.0], [9.8, -7.6], [9.6, -3.4], [-10.6, -3.6]]
PIP_SLOT = [-5.4, -1.6]
AWNINGS = [["#b5402f", "#efe2c0"], ["#4f7d4a", "#efe2c0"], ["#c98a2a", "#efe2c0"], ["#4a6a8a", "#dfe6ea"], ["#6a4a7a", "#efe2c0"], ["#7a6448", "#efe2c0"]]
ROOFS = {"thatch": "thatch", "slate": "slate", "tile": "tiles"}


def tex(name, rep=(1, 1), **kw):
    return {"texture": name, "repeat": list(rep), **kw}


def _box(size, at, mat, **kw):
    return {"shape": "box", "size": size, "at": at, "material": mat, **kw}


def on_build(ctx):
    d, r = ctx["details"], random.Random(ctx["seed"])
    props = set(d.get("props") or [])
    s = [{"shape": "box", "size": [32, 1, 20], "at": [0, -0.5, -4], "faces": {"top": tex("cobble", (16, 10)), "side": tex("stone", (16, 1))},
          "tip": {"title": "$label", "text": "$description"}},
         {"shape": "box", "size": [40, 1, 10], "at": [0, -1.6, 11], "faces": {"top": tex("grass", (20, 5)), "side": tex("cliff", (20, 1))}},
         {"shape": "box", "size": [46, 5, 8], "at": [0, 1.0, -22], "faces": {"top": tex("grass", (23, 4)), "side": tex("cliff", (23, 2))}}]
    parts = [{"part": "pine-tree", "params": {"scale": round(1.2 + r.random() * 0.8, 1)}, "at": [round(-22 + i * 2.9 + r.random(), 2), 3.5, round(-21 - r.random() * 2, 2)], "role": f"pine-{i}"}
             for i in range(16)]
    # houses round the square, lit at night
    hx = -14.2
    while hx < 13:
        w, h = 3.4 + r.random() * 1.6, 3.6 + r.random() * 1.4
        x = hx + w / 2
        hx += w + 0.2
        roof = ROOFS.get(d.get("roof"), "shingles") if r.random() > 0.4 else ("thatch" if r.random() > 0.5 else "shingles")
        s.append(_box([round(w, 2), round(h, 2), 3], [round(x, 2), round(h / 2, 2), -13.5], tex("plaster", (round(w / 2), 1))))
        s += [_box([round(w + 0.6, 2), 0.3, 2.4], [round(x, 2), round(h + 0.6, 2), z], tex(roof, (3, 2)), rot=[tilt, 0, 0]) for tilt, z in ((40.1, -12.6), (-40.1, -14.4))]
        s += [{"shape": "plane", "size": [0.8, 0.8], "at": [round(x + dx, 2), round(h * 0.68, 2), -11.99],
               "material": {"texture": "window", "emissive": "#ffb050", "lamp": 0.9 if r.random() > 0.3 else 0.3}} for dx in (-w / 4, w / 4)]
        s.append({"shape": "plane", "size": [0.9, 1.4], "at": [round(x, 2), 0.7, -11.99], "material": {"texture": "door"}})
    if "well" in props or r.random() > 0.4:
        parts.append({"part": "well", "at": [0, 0, -5.2], "role": "well"})
    if "barrow" in props:
        wood = tex("planks", (2, 1), color="#7a5236")
        s.append(_box([1.8, 0.5, 1.0], [6.2, 0.75, -2.0], wood, tip={"title": "A barrow", "text": "Wheeled in at dawn."}))
        s += [{"shape": "cylinder", "radius": 0.35, "top": 0.35, "height": 0.1, "segments": 10, "at": [6.2 + dx, 0.35, -1.4], "rot": [90, 0, 0], "material": wood} for dx in (-0.7, 0.7)]
        s += [{"shape": "sphere", "radius": 0.16, "segments": 6, "at": [round(5.6 + (i % 3) * 0.45, 2), 1.1, round(-2.3 + (i // 3) * 0.3, 2)],
               "material": {"color": ["#6fa047", "#d8b24a", "#8a4a6a"][i % 3]}} for i in range(9)]
    if "crates" in props:
        s += [_box([0.8, 0.7, 0.8], [x + 1, 0.35 + (0.7 if i == 2 else 0), z + 4], tex("planks", color="#9a7048")) for i, (x, z) in enumerate([[-12.5, -4], [-11.6, -4.2], [-12.1, -3.2]])]
    cols = ["#b5402f", "#e8b04a", "#4f7d4a", "#4a6a8a", "#efe2c0"]
    for i in range(28):
        k = (i % 14) / 13
        s.append({"shape": "cone", "radius": 0.2, "height": 0.4, "segments": 3, "at": [round((-13 if i < 14 else 0) + 13 * k, 2), round(4.4 - math.sin(k * math.pi) * 0.9, 2), -11.3],
                  "rot": [180, 0, 0], "material": {"color": cols[i % 5]}, "sway": True, "shadow": False})
    for x, z in ((-2.8, -3.0), (3.0, -3.0)):
        s += [_box([0.14, 2.6, 0.14], [x, 1.3, z], tex("planks", (1, 2), color="#3f3326")),
              _box([0.32, 0.4, 0.32], [x, 2.75, z], {"color": "#222222", "emissive": "#ffc070", "lamp": True}),
              {"shape": "light", "color": "#ffb066", "strength": 1, "range": 8, "at": [x, 2.6, z + 0.3], "lamp": True}]
    # the stalls: one for each of today's booths, in turn, and Pip's own
    anchors = []
    for i, (x, z) in enumerate(SLOTS):
        c1, c2 = AWNINGS[i % len(AWNINGS)]
        parts.append({"part": "stall", "params": {"color": c1, "color2": c2}, "at": [x, 0, z], "role": f"stall-{i + 1}", "when": [f"booth-{i + 1}"]})
        anchors.append({"id": f"booth-{i + 1}", "type": "surface", "tags": ["booth", "reserved"], "at": [x, 0.97, z - 0.2], "extent": [2.3, 0.6]})
    parts.append({"part": "stall", "params": {"color": "#d8c8a4", "color2": "#cdbb94", "own": True}, "at": [PIP_SLOT[0], 0, PIP_SLOT[1]], "role": "pips"})
    PX, PZ = PIP_SLOT[0], PIP_SLOT[1]
    s.append(_box([3.0, 0.3, 1.1], [PX, 0.9, PZ], None, hitbox=True, tip={"title": "Pip's stall", "text": "$stall"}))
    anchors += [{"id": "pip-stall", "type": "surface", "tags": ["pip-stall", "stall", "pip", "counter"], "at": [PX, 0.97, PZ - 0.1], "extent": [2.6, 0.9]},
                {"id": "pip", "type": "ground", "tags": ["pip", "reserved"], "at": [-1.5, 0.0, -1.0], "extent": [2, 1]},
                {"id": "crowd", "type": "ground", "tags": ["outside", "crowd", "reserved"], "at": [1.0, 0.0, -4.0], "extent": [17, 4.5]},
                {"id": "square", "type": "ground", "tags": ["outside", "square"], "at": [0.5, 0.0, -5.5], "extent": [6.0, 2.0]}]
    return {"parts": parts, "shapes": s, "anchors": anchors, "camera": {"at": [0, 13, 22], "look": [0, 0.4, -3]}}
