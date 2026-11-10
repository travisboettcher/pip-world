# A neighbor's home: their cottage opened like a dollhouse, with what they sell on a cabinet's shelves and what their record mentions (a
# lighthouse, a tide chart, a tin by the door, beehives, vegetables, books). By the water it stands on a marsh above mudflats the tide covers
# and uncovers, where curlews feed at low water and roost at high; inland, on a terrace in a meadow. Whoever lives here is about the house by
# day, at the table in the evening, out on the flats on a morning low tide, away at the market on their day (a note on the door).
import random

CX0, CX1, CZ0, CZ1 = -5.0, 3.5, -9.5, -4.4


def _box(size, at, mat, **kw):
    return {"shape": "box", "size": size, "at": at, "material": mat, **kw}


def _ground(size, at, top, side, **kw):
    return {"shape": "box", "size": size, "at": at, "faces": {"top": top, "side": side}, **kw}


def tex(name, rep=(1, 1), **kw):
    return {"texture": name, "repeat": list(rep), **kw}


def on_build(ctx):
    d = ctx["details"]
    r = random.Random(ctx["seed"])
    rnd = lambda a, b: round(a + r.random() * (b - a), 2)
    props, coastal = set(d.get("props") or []), bool(d.get("coastal"))
    s, parts = [], []
    if coastal:
        s += [_ground([26, 1.2, 15], [6, -0.6, -3.5], tex("marsh", (13, 8)), tex("cliff", (13, 1))),
              _ground([22, 0.6, 30], [-18, -0.85, -5], tex("mud", (11, 15)), tex("mud", (11, 1))),
              _ground([40, 1, 14], [6, -1.6, 10], tex("marsh", (20, 7)), tex("mud", (20, 1))),
              _box([40, 1, 40], [-26, -1.22, -6], tex("sea", (18, 20), rough=0.25, opacity=0.88), animate="tide", speed=0.01, shadow=False,
                   tip={"title": "The sea", "text": "It comes in over the mudflats and goes out again."})]
        if "shingle" in props:
            s.append(_ground([14, 0.9, 3.5], [-9.5, -0.35, -11.5], tex("pebbles", (7, 2)), tex("pebbles", (7, 1)), rot=[0, 6.9, 0],
                             tip={"title": "The shingle bank", "text": "It grows overnight, and moves the paths along the shore."}))
            s += [_box([0.25, 1.4 + (i % 2) * 0.2, 0.25], [round(-13.5 + g * 3.2 - i * 0.55, 2), -0.4, round(-9.5 + i * 0.9, 2)], tex("planks", color="#3f3326"))
                  for g in range(3) for i in range(9)]
        for i in range(60 if "reeds" in props else 25):
            left = i < 34
            s.append({"shape": "sprite", "art": "reed", "size": [0.5, 1.0], "shadow": False,
                      "at": [rnd(-6.8, -5.2) if left else rnd(-4, 18), -0.1 if left else 0.45, rnd(-10, 4) if left else rnd(2.4, 4.0)]})
        if "birds" in props:
            for i in range(9):
                tip = {"title": "A curlew", "text": "Feeding on the flats while the tide is out."}
                s.append({"shape": "sprite", "art": "curlew", "size": [0.6, 0.48], "at": [rnd(-15, -8), -0.31, rnd(-3, 3)], "animate": "wander", "speed": 0.02,
                          "when": "low-tide", "tip": tip})
                s.append({"shape": "sprite", "art": "curlew", "size": [0.6, 0.48], "at": [round(-12 + i * 0.6, 2), 0.4, round(-10.3 - (i % 3) * 0.4, 2)],
                          "when": "high-tide", "tip": {"title": "A curlew", "text": "Roosting on the bank until the water goes out."}})
    else:
        s += [_ground([30, 2, 16], [0, -1, -4], tex("grass", (15, 8)), tex("cliff", (15, 1))), _ground([40, 1, 12], [0, -2.5, 9], tex("grass", (20, 6)), tex("cliff", (20, 1)))]
        parts += [{"part": "round-tree", "params": {"scale": 1.1}, "at": [10.5, 0, -6], "role": "tree-a"},
                  {"part": "round-tree", "params": {"scale": 0.9}, "at": [-9, 0, -8.5], "role": "tree-b"}]
        parts += [{"part": "pine-tree", "params": {"scale": round(rnd(1.2, 1.9), 1)}, "at": [round(-15 + i * 2.6 + r.random(), 2), 0, rnd(-14.5, -12.5)], "role": f"pine-{i}"} for i in range(12)]
        if "beehives" in props:
            s += [_box([0.7, 0.9, 0.7], [7 + i * 1.3, 0.45, -7.5], tex("planks", color="#d8c08a"), tip={"title": "A beehive", "text": "Humming, on a warm day."}) for i in range(3)]
    if "lighthouse" in props:
        s += [_ground([4, 1.6, 4], [-11, -0.2, -16], tex("stone", (2, 1)), tex("stone", (2, 1))),
              {"shape": "cylinder", "radius": 1.15, "top": 0.85, "height": 7, "segments": 10, "at": [-11, 4.1, -16], "material": tex("whitewash", (3, 4)),
               "tip": {"title": "The lighthouse", "text": "It stands over the water on its rock."}},
              {"shape": "cylinder", "radius": 0.96, "top": 0.93, "height": 0.8, "segments": 10, "at": [-11, 5.4, -16], "material": {"color": "#b5402f"}},
              {"shape": "cylinder", "radius": 0.7, "height": 0.9, "segments": 10, "at": [-11, 8.0, -16], "material": {"color": "#444036", "emissive": "#fff0b0", "lamp": 1.3}},
              {"shape": "cone", "radius": 0.95, "height": 0.8, "segments": 10, "at": [-11, 8.8, -16], "material": {"color": "#2f3a3e"}},
              {"shape": "plane", "size": [14, 1.1], "at": [-11, 8.0, -16], "material": {"color": "#fff2c0", "beam": True}, "animate": "spin", "speed": 0.6}]
    # the cottage and what is in it
    walls = d.get("walls") or ("whitewash" if coastal else "plaster")
    roof = d.get("roof") or ("slate" if coastal else "thatch")
    parts.append({"part": "cutaway", "params": {"width": CX1 - CX0, "depth": CZ1 - CZ0, "height": 3.0, "walls": walls, "roof": roof, "door": True},
                  "at": [(CX0 + CX1) / 2, 0, (CZ0 + CZ1) / 2], "role": "cottage"})
    cab = tex("planks", (2, 2), color="#6b4a30")
    s += [{"shape": "box", "size": [8.5, 0.12, 5.1], "at": [(CX0 + CX1) / 2, 0.13, (CZ0 + CZ1) / 2], "hitbox": True, "tip": {"title": "$resident's home", "text": "$description"}},
          _box([0.7, 2.2, 0.7], [CX0 + 1.2, 4.4, CZ0 + 0.5], tex("stone", (1, 2))),
          {"shape": "plane", "size": [1.2, 1.2], "at": [-1.6, 1.9, CZ0 + 0.21], "material": {"texture": "window", "emissive": "#ffb050", "lamp": True},
           "tip": {"title": "The window", "text": "It faces the water." if coastal else "It looks out on the garden."}},
          {"shape": "light", "color": "#ffb066", "strength": 1, "range": 8, "at": [0.5, 2.2, -6.0], "lamp": True},
          _box([2.6, 2.4, 0.6], [-3.4, 1.2, CZ0 + 0.55], cab)]
    s += [_box([2.4, 0.06, 0.55], [-3.4, round(0.55 + k * 0.7, 2), CZ0 + 0.85], cab) for k in range(3)]
    s += [_box([2.6, 2.4, 0.9], [-3.4, 1.2, CZ0 + 0.9], None, hitbox=True, tip={"title": "$resident's cabinet", "text": "$wares"}),
          _box([1.8, 0.12, 1.1], [0.2, 0.85, -6.6], tex("planks", (2, 1), color="#8a6440"), tip={"title": "The table", "text": "An open book, kept up every day." if "books" in props else "Where they sit of an evening."})]
    s += [_box([0.12, 0.8, 0.12], [0.2 + dx, 0.4, -6.6 + dz], cab) for dx in (-0.75, 0.75) for dz in (-0.45, 0.45)]
    if "books" in props:
        s.append({"shape": "plane", "size": [0.8, 0.5], "at": [0.0, 0.92, -6.5], "rot": [-90, 0, 0], "material": {"texture": "book"}})
    s += [_box([1.0, 1.0, 0.8], [2.6, 0.55, CZ0 + 0.7], {"color": "#2f2c2a", "rough": 0.6, "metal": 0.3}),
          _box([0.5, 0.2, 0.05], [2.6, 0.5, CZ0 + 1.12], {"color": "#2a2624", "emissive": "#ff8a3a", "rough": 0.6, "lamp": 0.8}),
          _box([0.18, 1.6, 0.18], [2.6, 1.85, CZ0 + 0.6], {"color": "#2f2c2a"})]
    if "tide chart" in props:
        s.append({"shape": "plane", "size": [1.3, 0.8], "at": [0.6, 2.1, CZ0 + 0.21], "material": {"texture": "chart"}, "tip": {"title": "A tide chart", "text": "High and low water, marked by hand."}})
    if "tin" in props:
        s.append({"shape": "cylinder", "radius": 0.22, "height": 0.36, "segments": 10, "at": [CX1 - 0.6, 0.3, CZ0 + 2.9], "material": {"color": "#c9a24a", "metal": 0.6, "rough": 0.4},
                  "tip": {"title": "A tin by the door", "text": "Something kept, by the door."}})
    s.append(_ground([1.4, 0.25, 1.4], [CX1 + 1.0, 0.12, CZ0 + 2.4], tex("stone"), tex("stone"), tip={"title": "The step", "text": "Worn smooth by the door."}))
    if "vegetables" in props:
        s.append(_ground([3, 0.2, 1.4], [6.4, 0.1, -7.6], tex("soil", (2, 1)), tex("planks", (2, 1), color="#5a3d27")))
        s += [{"shape": "sprite", "art": "carrots", "size": [0.4, 0.5], "at": [round(5.3 + i * 0.45, 2), 0.45, -7.6]} for i in range(6)]
    s += [_box([10, 0.12, 1.2], [9, 0.08, -2.2], tex("planks", (1, 6), color="#7a6448")), _box([2.6, 0.12, 1.2], [CX1 + 2.2, 0.08, CZ0 + 2.4], tex("planks", (1, 6), color="#7a6448")),
          {"shape": "sprite", "art": "note", "size": [0.45, 0.45], "at": [CX1 + 0.62, 1.4, CZ0 + 2.1], "shadow": False, "when": "resident-away",
           "tip": {"title": "A note on the door", "text": "$note"}}]
    anchors = [{"id": "resident", "type": "floor", "tags": ["inside", "resident", "reserved"], "at": [-3.0, 0.12, CZ0 + 1.6], "extent": [1, 1]},
               {"id": "resident-evening", "type": "floor", "tags": ["inside", "resident-evening", "reserved"], "at": [0.9, 0.12, -5.6], "extent": [1, 1]},
               {"id": "visitor", "type": "floor", "tags": ["inside", "visitor", "reserved"], "at": [-1.2, 0.12, CZ0 + 2.3], "extent": [1, 1]},
               {"id": "pip", "type": "ground", "tags": ["outside", "pip", "reserved"], "at": [CX1 + 2.4, 0.12, CZ0 + 3.0], "extent": [2, 1]},
               {"id": "people", "type": "ground", "tags": ["outside", "people", "reserved"], "at": [CX1 + 1, 0, CZ0 + 3.8], "extent": [4, 1]},
               *({"id": f"wares-{k}", "type": "surface", "tags": ["inside", "wares", "reserved"], "at": [-3.4, round(0.58 + k * 0.7, 2), CZ0 + 0.9], "extent": [2.0, 0.4]} for k in range(3)),
               # where module objects go (as the hand-written scene published)
               {"id": "back-wall", "type": "wall", "tags": ["inside", "back"], "at": [-0.5, 2.0, -9.33], "normal": [0, 0, 1], "extent": [0.8, 0.8]},
               {"id": "table", "type": "surface", "tags": ["inside", "table"], "at": [0.2, 0.91, -6.6], "extent": [1.6, 0.9]},
               {"id": "floor", "type": "floor", "tags": ["inside"], "at": [-0.5, 0.12, -5.2], "extent": [5.0, 1.0]},
               {"id": "garden", "type": "ground", "tags": ["outside", "garden"], "at": [6.4, 0.0, -3.0], "extent": [4.0, 1.5]}]
    if coastal:
        anchors.append({"id": "flats", "type": "ground", "tags": ["outside", "resident-walk", "reserved"], "at": [-11, -0.55, -2.5], "extent": [5.8, 6]})
    return {"parts": parts, "shapes": s, "anchors": anchors, "camera": {"at": [0, 13, 19], "look": [0, 0.2, -4.6]}}
