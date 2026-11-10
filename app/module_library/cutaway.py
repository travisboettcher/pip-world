# A building opened like a dollhouse: floor, back and side walls (inner faces drawn on the inside), a back roof slope and gable ends,
# timber posts and a sill along the open front, a door in the right wall, and daylight coming in. No top beam: from the camera's angle
# it would cross the room. Its back wall, floor and front are anchors.
OUTER = {"plaster": ("plaster", [2, 1]), "whitewash": ("whitewash", [4, 2]), "stone": ("stone", [4, 2]), "planks": ("planks", [4, 2]),
         "brick": ("brick", [4, 2])}
ROOFS = {"thatch": "thatch", "slate": "slate", "shingle": "shingles", "tile": "tiles"}


def on_build(ctx):
    p = ctx["params"]
    w, d, h = float(p["width"]), float(p["depth"]), float(p["height"])
    x0, x1, z0, z1 = -w / 2, w / 2, -d / 2, d / 2
    tex, rep = OUTER.get(p["walls"], OUTER["plaster"])
    outer = {"texture": tex, "repeat": rep}
    inner = {"texture": "inner", "repeat": [6, 2]}
    timber = {"texture": "planks", "repeat": [1, 2], "color": "#4a2f1f"}
    s = [{"shape": "box", "size": [w, 0.12, d], "at": [0, 0.06, 0], "faces": {"top": {"texture": "floor", "repeat": [5, 3]},
                                                                             "side": {"texture": "planks", "repeat": [5, 1], "color": "#5a3d27"}}},
         {"shape": "box", "size": [w, h, 0.3], "at": [0, h / 2, z0], "material": outer},
         {"shape": "plane", "size": [w - 0.3, h], "at": [0, h / 2, z0 + 0.16], "material": inner},
         {"shape": "box", "size": [0.3, h, d], "at": [x0, h / 2, 0], "material": outer},
         {"shape": "plane", "size": [d - 0.3, h], "at": [x0 + 0.16, h / 2, 0], "rot": [0, 90, 0], "material": inner}]
    if p["door"]:
        back = d - 3.5
        s += [{"shape": "box", "size": [0.3, h, 1.6], "at": [x1, h / 2, z0 + 0.8], "material": outer},
              {"shape": "box", "size": [0.3, h, back], "at": [x1, h / 2, z1 - back / 2], "material": outer},
              {"shape": "box", "size": [0.3, 0.9, 1.9], "at": [x1, h - 0.45, z0 + 2.55], "material": outer},
              {"shape": "plane", "size": [1.4, 2.1], "at": [x1 + 0.55, 1.05, z0 + 2.0], "rot": [0, -41.3, 0], "material": {"texture": "door", "double": True}}]
    else:
        s.append({"shape": "box", "size": [0.3, h, d], "at": [x1, h / 2, 0], "material": outer})
    s.append({"shape": "light", "color": "#fff0dc", "strength": 0.9, "range": w * 1.3, "at": [0, h * 0.8, z1 - 0.5]})
    s += [{"shape": "box", "size": [0.4, h, 0.4], "at": [x, h / 2, z1], "material": timber} for x in (x0, x1)]
    s.append({"shape": "box", "size": [w + 0.4, 0.3, 0.4], "at": [0, 0.15, z1], "material": timber})
    s.append({"shape": "box", "size": [w + 1.1, 0.32, d * 0.72], "at": [0, h + d * 0.2, z0 + d * 0.22], "rot": [-35.5, 0, 0],
              "material": {"texture": ROOFS.get(p["roof"], "thatch"), "repeat": [5, 2]}})
    gable = {"texture": "whitewash", "repeat": [2, 1]} if p["walls"] == "whitewash" else {"texture": "planks", "repeat": [2, 1], "color": "#6b4529"}
    s += [{"shape": "gable", "width": d, "height": d * 0.42, "at": [x, h, 0], "rot": [0, -90, 0], "material": {**gable, "double": True}}
          for x in (x0 - 0.15, x1 + 0.15)]
    return {"shapes": s,
            "anchors": [{"id": "back-wall", "type": "wall", "tags": ["inside", "back"], "at": [0, h * 0.6, z0 + 0.17], "normal": [0, 0, 1],
                         "extent": [w - 1.5, h * 0.4]},
                        {"id": "floor", "type": "floor", "tags": ["inside"], "at": [0, 0.12, z1 - 0.9], "extent": [w - 1.0, 0.8]},
                        {"id": "front", "type": "ground", "tags": ["outside", "front"], "at": [0, 0, z1 + 1.2], "extent": [w, 1.0]}]}
