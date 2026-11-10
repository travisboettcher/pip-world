# The woods, as a layout: the same land and trees the hand-written outdoors scene draws for a wood, from parts. A clearing in front,
# round trees scattered behind it and two at the edges, pines further back; where Pip stands, and where finds lie, are anchors.
import random


def on_build(ctx):
    r = random.Random(ctx["seed"])
    parts = []
    for i in range(9):
        parts.append({"part": "round-tree", "params": {"scale": round(0.8 + r.random() * 0.6, 1)},
                      "at": [round(-13 + r.random() * 26, 2), 0, round(-11 + r.random() * 5, 2)], "role": f"tree-{i}"})
    parts += [{"part": "round-tree", "params": {"scale": 1.0}, "at": [-11, 0, 1.5], "role": "tree-left"},
              {"part": "round-tree", "params": {"scale": 1.1}, "at": [11.5, 0, 0.5], "role": "tree-right"}]
    for i in range(18):
        parts.append({"part": "pine-tree", "params": {"scale": round(1.1 + r.random() * 0.8, 1)},
                      "at": [round(-14 + r.random() * 28, 2), 0, round(-12.5 - r.random() * 3, 2)], "role": f"pine-{i}"})
    land = {"shape": "box", "size": [30, 2, 16], "at": [0, -1, -4], "faces": {"top": {"texture": "grass", "repeat": [15, 8]},
                                                                           "side": {"texture": "cliff", "repeat": [15, 1]}},
            "tip": {"title": "$label", "text": "$description"}}
    below = {"shape": "box", "size": [40, 1, 12], "at": [0, -2.5, 9], "faces": {"top": {"texture": "grass", "repeat": [20, 6]},
                                                                             "side": {"texture": "cliff", "repeat": [20, 1]}}}
    anchors = [{"id": "pip", "type": "ground", "tags": ["outside", "pip", "people"], "at": [-1.5, 0, 0.5], "extent": [10, 3]},
               {"id": "finds", "type": "ground", "tags": ["outside", "finds"], "at": [-1, 0, -2.5], "extent": [18, 6]},
               {"id": "clearing", "type": "ground", "tags": ["outside", "clearing"], "at": [0, 0, -3], "extent": [12, 3]}]
    return {"parts": parts, "shapes": [land, below], "anchors": anchors}
