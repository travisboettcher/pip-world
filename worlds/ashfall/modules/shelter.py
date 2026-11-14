# The shelter: a concrete room under the city, opened like a dollhouse (racks, a bench and its tools, a cot, a hanging bulb), the stairwell
# up to the street, rubble and a dead tree or two around it. What changes with the world has anchors: creations on the wall, the rack and
# the floor, and where the agent sits, sleeps, works and stands.
import random

WX0, WX1, WZ0, WZ1, WH = -10.5, -1.5, -7.0, -1.6, 3.0
WMID, RZ = (WX0 + WX1) / 2, (WZ0 + WZ1) / 2


def _box(size, at, mat, **kw):
    return {"shape": "box", "size": size, "at": at, "material": mat, **kw}


def _ground(size, at, top, side, **kw):
    return {"shape": "box", "size": size, "at": at, "faces": {"top": top, "side": side}, **kw}


def on_build(ctx):
    r = random.Random(41)
    concrete = lambda rep: {"texture": "stone", "repeat": rep, "color": "#8a8a86"}
    dirt = lambda rep: {"texture": "cobble", "repeat": rep, "color": "#6b6458"}
    steel = {"color": "#5c5f62", "metal": 0.6, "rough": 0.5}
    s = [_ground([30, 2, 16], [0, -1, -4], dirt([15, 8]), concrete([15, 1])),
         _ground([40, 1, 12], [0, -2.5, 9], dirt([20, 6]), concrete([20, 1])),
         _ground([40, 4, 6], [0, 1.2, -14], dirt([20, 3]), concrete([20, 2])),
         # the shelter
         _ground([WX1 - WX0, 0.12, WZ1 - WZ0], [WMID, 0.06, RZ], concrete([5, 3]), concrete([5, 1]),
                 tip={"title": "The shelter", "text": "Home: a bench, a cot, a rack, and whatever is being mended."}),
         _box([WX1 - WX0, WH, 0.4], [WMID, WH / 2, WZ0], concrete([4, 2])),
         _box([0.4, WH, WZ1 - WZ0], [WX0, WH / 2, RZ], concrete([3, 2])),
         _box([0.4, WH, 1.6], [WX1, WH / 2, WZ0 + 0.8], concrete([1, 2])), _box([0.4, WH, 1.9], [WX1, WH / 2, WZ1 - 0.95], concrete([1, 2])),
         _box([0.4, 0.8, 1.9], [WX1, WH - 0.4, RZ - 0.15], concrete([1, 1])),
         _box([0.12, 2.2, 1.4], [WX1 + 0.3, 1.1, RZ - 0.15], steel, tip={"title": "The door", "text": "Steel, with a bar across it at night."}),
         _box([WX1 - WX0 + 0.8, 0.5, WZ1 - WZ0 + 0.8], [WMID, WH + 0.25, RZ], concrete([5, 1]))]
    # the stairwell up to the street
    s += [_ground([1.6, 0.4, 0.6], [0.4 + i * 0.6, 0.2 + i * 0.4, -3.0], concrete([1, 1]), concrete([1, 1])) for i in range(4)]
    # inside: the rack, the bench and its tools, the cot, the bulb
    s += [_box([3.2, 0.1, 0.5], [-8.4, 2.1, WZ0 + 0.45], steel), _box([3.2, 0.1, 0.5], [-8.4, 1.3, WZ0 + 0.45], steel)]
    for i, (c, w, h) in enumerate([("#a33b2a", 0.3, 0.36), ("#6b7b5a", 0.34, 0.3), ("#b0a070", 0.26, 0.4), ("#6b7b5a", 0.34, 0.3)]):
        s.append(_box([w, h, w], [-9.6 + i * 0.7, 2.15 + h / 2, WZ0 + 0.45], {"color": c, "rough": 0.6}))
    s += [_box([3.2, 1.6, 0.6], [-8.4, 1.7, WZ0 + 0.45], None, hitbox=True, tip={"title": "Belongings", "text": "$belongings"}),
          _box([3.6, 0.2, 1.2], [-6.4, 1.0, WZ0 + 1.3], {"color": "#6a5a44", "rough": 0.8}, tip={"title": "The bench", "text": "$project"})]
    s += [_box([0.16, 0.9, 0.16], [x, 0.45, WZ0 + 1.3 + dz], steel) for x, dz in ((-7.9, -0.4), (-4.9, -0.4), (-7.9, 0.4), (-4.9, 0.4))]
    s += [_box([0.9, 0.35, 2.0], [-9.6, 0.3, WZ1 - 1.2], {"color": "#4f5a48", "rough": 0.9}, tip={"title": "The cot", "text": "Army surplus, and better than the floor."}),
          _box([0.04, 0.9, 0.04], [-6.2, WH - 0.45, WZ0 + 2.2], steel),
          {"shape": "light", "color": "#ffd8a0", "strength": 0.9, "range": 8, "at": [-6.2, WH - 1.2, WZ0 + 2.4], "lamp": True},
          _box([0.25, 0.3, 0.25], [-6.2, WH - 1.0, WZ0 + 2.2], {"color": "#333333", "emissive": "#ffe0a0", "lamp": 1.0})]
    # rubble above, and a few dead trees
    for i in range(18):
        x, z = round(-13 + r.random() * 26, 2), round(6 + r.random() * 4, 2)
        w = round(0.4 + r.random() * 1.2, 2)
        s.append(_box([w, round(0.2 + r.random() * 0.6, 2), w], [x, -1.9, z], concrete([1, 1]), rot=[0, round(r.random() * 90), 0]))
    parts = [{"part": "scrap-heap", "params": {}, "at": [8.5, 0, -4.0], "role": "heap"}]
    anchors = [{"id": "clock-1", "type": "wall", "tags": ["inside", "clock"], "at": [-2.4, 1.8, WZ0 + 0.22], "extent": [0.9, 1.4]},
               {"id": "clock-2", "type": "wall", "tags": ["inside", "clock"], "at": [-3.6, 1.8, WZ0 + 0.22], "extent": [0.9, 1.4]},
               {"id": "shelf", "type": "surface", "tags": ["inside", "shelf"], "at": [-8.1, 2.15, WZ0 + 0.45], "extent": [3.2, 0.4]},
               {"id": "walkers", "type": "floor", "tags": ["inside", "walkers"], "at": [-7.8, 0.12, -2.9], "extent": [3.2, 1.2]},
               {"id": "seat", "type": "surface", "tags": ["inside", "seat"], "at": [-9.6, 0.5, WZ1 - 1.2], "extent": [0.7, 0.7]},
               {"id": "workbench", "type": "floor", "tags": ["inside", "workbench"], "at": [-6.6, 0.06, WZ0 + 2.25], "extent": [1.0, 0.6]},
               {"id": "pip", "type": "floor", "tags": ["inside", "pip"], "at": [-4.6, 0.06, WZ0 + 2.9], "extent": [1.0, 0.6]},
               {"id": "back-wall", "type": "wall", "tags": ["inside", "back"], "at": [-5.25, 2.0, -6.78], "normal": [0, 0, 1], "extent": [0.9, 0.9]},
               {"id": "bench", "type": "surface", "tags": ["inside", "bench"], "at": [-5.6, 1.1, -5.8], "extent": [1.8, 0.6]},
               {"id": "floor", "type": "floor", "tags": ["inside"], "at": [-6.0, 0.12, -3.4], "extent": [4.0, 1.2]},
               {"id": "yard", "type": "ground", "tags": ["outside", "yard"], "at": [3.6, 0.04, -1.2], "extent": [5.0, 1.5]}]
    for a in anchors[:7]:                                   # where the scene draws the agent and its creations: not for modules
        a["tags"].append("reserved")
    anchors = anchors[7:] + anchors[:7]
    return {"parts": parts, "shapes": s, "anchors": anchors, "camera": {"at": [0, 13, 22], "look": [0, 0.2, -1.5]}}
