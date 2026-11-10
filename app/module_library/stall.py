# A market stall: a trestle counter, four posts, and a striped awning in two colours, rolled up while the market is shut. The counter is a
# surface to set things on. Pip's own stall (`own`) has its awning out only while Pip has set something out.
def on_build(ctx):
    p = ctx["params"]
    wood = {"texture": "planks", "repeat": [2, 1], "color": "#8a6440"}
    post = {"texture": "planks", "repeat": [1, 2], "color": "#5a3d27"}
    stripes = {"texture": "stripes", "color": p["color"], "color2": p["color2"]}
    shapes = [{"shape": "box", "size": [3.0, 0.14, 1.1], "at": [0, 0.9, 0], "material": wood}]
    shapes += [{"shape": "box", "size": [0.12, 0.84, 0.12], "at": [dx, 0.42, dz], "material": post} for dx in (-1.35, 1.35) for dz in (-0.45, 0.45)]
    shapes += [{"shape": "box", "size": [0.14, h, 0.14], "at": [dx, h / 2, dz], "material": post} for dx in (-1.45, 1.45) for dz, h in ((-0.75, 2.6), (0.75, 2.0))]
    shapes.append({"shape": "box", "size": [3.3, 0.08, 1.9], "at": [0, 2.35, 0], "rot": [18.3, 0, 0], "material": stripes,
                   "when": ["open", "pip-stall"] if p.get("own") else ["open"]})
    rolled = {"shape": "cylinder", "radius": 0.16, "top": 0.16, "height": 3.2, "segments": 8, "at": [0, 2.55, -0.75], "rot": [0, 0, 90], "material": stripes}
    shapes.append({**rolled, "when": ["shut"]})
    if p.get("own"):
        shapes.append({**rolled, "when": ["no-pip-stall"]})
    return {"shapes": shapes,
            "anchors": [{"id": "counter", "type": "surface", "tags": ["stall", "counter"], "at": [0, 0.97, -0.1], "extent": [2.6, 0.9]},
                        {"id": "front", "type": "ground", "tags": ["outside", "stall"], "at": [0, 0, 1.4], "extent": [3.0, 0.8]}]}
