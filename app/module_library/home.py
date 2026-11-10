# Pip's workshop and its garden: the workshop opened like a dollhouse (a shelf, the bench and its tools, a stool, a hanging lamp, a window),
# the garden behind its fence, the terrace, the stream and the bridge, a hill of pines behind and flowers along the edge. What changes with
# the world has anchors: the plots, Pip's creations (clocks on the wall, things on the shelf, walking things on the floor), and where Pip
# sits, sleeps, works, gardens and stands.
import random

WX0, WX1, WZ0, WZ1, WH = -10.5, -1.5, -7.0, -1.6, 3.4
WMID, RZ = (WX0 + WX1) / 2, (WZ0 + WZ1) / 2


def _box(size, at, mat, **kw):
    return {"shape": "box", "size": size, "at": at, "material": mat, **kw}


def _ground(size, at, top, side, **kw):
    return {"shape": "box", "size": size, "at": at, "faces": {"top": top, "side": side}, **kw}


def on_build(ctx):
    r = random.Random(77)
    grass = lambda rep: {"texture": "grass", "repeat": rep}
    cliff = lambda rep: {"texture": "cliff", "repeat": rep}
    planks = lambda rep, c: {"texture": "planks", "repeat": rep, "color": c}
    outer, inner, timber = {"texture": "plaster", "repeat": [2, 1]}, {"texture": "inner", "repeat": [6, 2]}, planks([1, 2], "#4a2f1f")
    wood = planks([3, 1], "#7a5236")
    s = [_ground([30, 2, 16], [0, -1, -4], grass([15, 8]), cliff([15, 1])),
         _ground([40, 1, 12], [0, -2.5, 9], grass([20, 6]), cliff([20, 1])),
         _box([40, 0.3, 2.6], [0, -2.0, 5.6], {"texture": "water", "repeat": [14, 2], "rough": 0.3}, animate="flow", speed=0.03),
         _ground([30, 0.6, 0.4], [0, -1.9, 4.2], {"texture": "stone", "repeat": [15, 1]}, {"texture": "stone", "repeat": [15, 1]}),
         _ground([40, 4, 6], [0, 1.2, -14], grass([20, 3]), cliff([20, 2])),
         _box([2.2, 0.25, 3.4], [6, -1.55, 5.6], planks([1, 4], "#8a6440"), tip={"title": "The bridge", "text": "Over the stream, and on to everywhere else."}),
         # the workshop
         _ground([WX1 - WX0, 0.12, WZ1 - WZ0], [WMID, 0.06, RZ], {"texture": "floor", "repeat": [5, 3]}, planks([5, 1], "#5a3d27"),
                 tip={"title": "The workshop", "text": "Pip's home: a bench, a stool, a shelf, and whatever is being made."}),
         _box([WX1 - WX0, WH, 0.3], [WMID, WH / 2, WZ0], outer),
         {"shape": "plane", "size": [WX1 - WX0 - 0.3, WH], "at": [WMID, WH / 2, WZ0 + 0.16], "material": inner},
         _box([0.3, WH, WZ1 - WZ0], [WX0, WH / 2, RZ], outer),
         {"shape": "plane", "size": [WZ1 - WZ0 - 0.3, WH], "at": [WX0 + 0.16, WH / 2, RZ], "rot": [0, 90, 0], "material": inner},
         _box([0.3, WH, 1.6], [WX1, WH / 2, WZ0 + 0.8], outer), _box([0.3, WH, 1.9], [WX1, WH / 2, WZ1 - 0.95], outer),
         _box([0.3, 1.0, 1.9], [WX1, WH - 0.5, RZ - 0.15], outer),
         {"shape": "plane", "size": [1.4, 2.2], "at": [WX1 + 0.6, 1.15, RZ - 0.15], "rot": [0, -38.4, 0], "material": {"texture": "door"}},
         _box([0.36, WH, 0.36], [WX0, WH / 2, WZ1], timber), _box([0.36, WH, 0.36], [WX1, WH / 2, WZ1], timber),
         _box([WX1 - WX0 + 0.36, 0.3, 0.36], [WMID, 0.15, WZ1], timber),
         _box([WX1 - WX0 + 1.2, 0.35, 3.8], [WMID, WH + 1.1, WZ0 + 1.2], {"texture": "thatch", "repeat": [5, 2]}, rot=[-35.5, 0, 0])]
    s += [{"shape": "gable", "width": WZ1 - WZ0, "height": 2.2, "at": [x, WH, RZ], "rot": [0, -90, 0], "material": {**planks([2, 1], "#6b4529"), "double": True}}
          for x in (WX0 - 0.15, WX1 + 0.15)]
    s += [_box([0.7, 2.4, 0.7], [WX0 + 1.4, WH + 1.6, WZ0 + 0.6], {"texture": "stone", "repeat": [1, 2]}),
          {"shape": "plane", "size": [1.3, 1.3], "at": [-3.9, 2.0, WZ0 + 0.18], "material": {"texture": "window", "emissive": "#ffb050", "lamp": 0.9},
           "tip": {"title": "The window", "text": "Looks out back, over the hill and the pines."}},
          # inside: the shelf and its jars, the bench and its tools, the stool, the hanging lamp
          _box([3.2, 0.12, 0.5], [-8.4, 2.25, WZ0 + 0.4], timber)]
    for i, (c, w, h) in enumerate([("#7fb3a8", 0.24, 0.42), ("#c9a24a", 0.3, 0.34), ("#9b6b9e", 0.24, 0.5), ("#7fb3a8", 0.32, 0.3), ("#b85c38", 0.24, 0.4), ("#cfcfcf", 0.3, 0.45)]):
        s.append(_box([w, h, w], [-9.6 + i * 0.5, 2.31 + h / 2, WZ0 + 0.4], {"color": c, "rough": 0.4}))
    s += [_box([3.2, 1.0, 0.6], [-8.4, 2.6, WZ0 + 0.4], None, hitbox=True, tip={"title": "Belongings", "text": "$belongings"}),
          _box([3.6, 0.2, 1.2], [-6.4, 1.1, WZ0 + 1.3], wood, tip={"title": "The bench", "text": "$project"})]
    s += [_box([0.18, 1.0, 0.18], [x, 0.5, WZ0 + 1.3 + dz], wood) for x, dz in ((-7.9, -0.4), (-4.9, -0.4), (-7.9, 0.4), (-4.9, 0.4))]
    s += [_box([0.6, 0.06, 0.12], [-7.2, 1.23, WZ0 + 1.2], {"color": "#b8b8b8", "metal": 0.7, "rough": 0.3}),
          _box([0.7, 0.12, 0.7], [-3.6, 0.75, WZ0 + 2.3], wood), _box([0.1, 0.7, 0.1], [-3.85, 0.35, WZ0 + 2.3], wood), _box([0.1, 0.7, 0.1], [-3.35, 0.35, WZ0 + 2.3], wood),
          _box([0.04, 1.0, 0.04], [-6.2, WH - 0.5, WZ0 + 2.2], timber),
          {"shape": "light", "color": "#ffb066", "strength": 1.1, "range": 9, "at": [-6.2, WH - 1.4, WZ0 + 2.4], "lamp": True},
          _box([0.4, 0.3, 0.4], [-6.2, WH - 1.1, WZ0 + 2.2], {"color": "#332211", "emissive": "#ffc070", "lamp": 1.1})]
    # the fence, the lantern, the paths and the steps
    fence = planks([1, 1], "#8a6440")
    s += [_box([0.14, 0.8, 0.14], [round(i * 0.85, 2), 0.4, -7.2], fence) for i in range(11)]
    s += [_box([8.6, 0.1, 0.08], [4.25, y, -7.2], fence) for y in (0.6, 0.3)]
    s += [_box([0.12, 1.8, 0.12], [-0.95, 0.9, -1.2], timber), _box([0.3, 0.36, 0.3], [-0.95, 1.9, -1.2], {"color": "#222222", "emissive": "#ffc070", "lamp": True}),
          {"shape": "light", "color": "#ffb066", "strength": 1, "range": 7, "at": [-0.7, 1.8, -0.9], "lamp": True}]
    cob = lambda rep: {"texture": "cobble", "repeat": rep}
    s += [_ground([1.6, 0.06, 1.6], [-0.6, 0.03, RZ], cob([1, 1]), cob([1, 1])), _ground([1.6, 0.06, 7], [0.2, 0.03, -0.1], cob([1, 4]), cob([1, 4])),
          _ground([6.2, 0.06, 1.6], [3.3, 0.04, 2.6], cob([4, 1]), cob([4, 1]))]
    s += [_ground([1.6, 0.5, 0.55], [6, -0.25 - i * 0.45, 3.6 + i * 0.5], {"texture": "stone"}, {"texture": "stone"}) for i in range(4)]
    # flowers along the edge (the coloured ones go in winter)
    for i in range(40):
        f, front = int(r.random() * 4), i < 26
        x = round(-13 + r.random() * 26, 2)
        at = [x, 0.2 if front else -1.8, round(2.4 + r.random() * 1.4 if front else 7.4 + r.random() * 2.5, 2)]
        if front and 5 < x < 7:
            continue
        s.append({"shape": "sprite", "art": "flower", "frame": f, "size": [0.42, 0.42], "at": at, "shadow": False, **({"when": "not-winter"} if f < 3 else {})})
    parts = [{"part": "round-tree", "params": {"scale": 1.15}, "at": [11.2, 0, -4.5], "role": "tree"}]
    for i in range(14):
        parts.append({"part": "pine-tree", "params": {"scale": round(1.2 + r.random() * 0.8, 1)}, "at": [round(-15 + i * 2.3 + r.random(), 2), 3.2, round(-12.5 - r.random() * 2, 2)], "role": f"pine-{i}"})
    anchors = [{"id": f"plot-{i + 1}", "type": "ground", "tags": ["outside", "plot"], "at": [round(1.4 + i * 2.4, 2), 0.12, -5.2], "extent": [1.9, 2.8]} for i in range(4)]
    anchors += [{"id": "clock-1", "type": "wall", "tags": ["inside", "clock"], "at": [-2.4, 1.9, WZ0 + 0.22], "extent": [0.9, 1.5]},
                {"id": "clock-2", "type": "wall", "tags": ["inside", "clock"], "at": [-3.6, 1.9, WZ0 + 0.22], "extent": [0.9, 1.5]},
                {"id": "shelf", "type": "surface", "tags": ["inside", "shelf"], "at": [-8.1, 2.3, WZ0 + 0.45], "extent": [3.2, 0.4]},
                {"id": "walkers", "type": "floor", "tags": ["inside", "walkers"], "at": [-7.8, 0.12, -2.9], "extent": [3.2, 1.2]},
                {"id": "seat", "type": "surface", "tags": ["inside", "seat"], "at": [-3.6, 0.76, WZ0 + 2.35], "extent": [0.7, 0.7]},
                {"id": "workbench", "type": "floor", "tags": ["inside", "workbench"], "at": [-6.6, 0.06, WZ0 + 2.25], "extent": [1.0, 0.6]},
                {"id": "garden-path", "type": "ground", "tags": ["outside", "garden-path"], "at": [3.8, 0.03, -3.4], "extent": [4.8, 0.5]},
                {"id": "pip", "type": "floor", "tags": ["inside", "pip"], "at": [-4.6, 0.06, WZ0 + 2.9], "extent": [1.0, 0.6]},
                # where module objects go (as the hand-written scene published): the back wall, the bench, the floor, the yard
                {"id": "back-wall-by-window", "type": "wall", "tags": ["inside", "back"], "at": [-5.25, 2.3, -6.83], "normal": [0, 0, 1], "extent": [0.9, 0.9]},
                {"id": "back-wall-over-bench", "type": "wall", "tags": ["inside", "back"], "at": [-7.15, 1.6, -6.83], "normal": [0, 0, 1], "extent": [0.7, 0.7]},
                {"id": "back-wall-under-shelf", "type": "wall", "tags": ["inside", "back"], "at": [-9.6, 1.5, -6.83], "normal": [0, 0, 1], "extent": [0.7, 0.7]},
                {"id": "bench", "type": "surface", "tags": ["inside", "bench"], "at": [-5.6, 1.2, -5.8], "extent": [1.8, 0.6]},
                {"id": "floor", "type": "floor", "tags": ["inside"], "at": [-6.0, 0.12, -3.4], "extent": [4.0, 1.2]},
                {"id": "yard", "type": "ground", "tags": ["outside", "yard"], "at": [3.6, 0.04, -1.2], "extent": [5.0, 1.5]}]
    for a in anchors[:-6]:                                  # where the scene draws Pip, its garden and its creations: not for modules
        a["tags"].append("reserved")
    anchors = anchors[-6:] + anchors[:-6]
    return {"parts": parts, "shapes": s, "anchors": anchors, "camera": {"at": [0, 13, 22], "look": [0, 0.2, -1.5]}}
