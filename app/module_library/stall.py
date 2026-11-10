# A market stall: a trestle counter, four posts, and a striped awning in two colours. The counter is a surface to set things on.
def on_build(ctx):
    wood = {"texture": "planks", "repeat": [2, 1], "color": "#8a6440"}
    post = {"texture": "planks", "repeat": [1, 2], "color": "#5a3d27"}
    shapes = [{"shape": "box", "size": [3.0, 0.14, 1.1], "at": [0, 0.9, 0], "material": wood}]
    shapes += [{"shape": "box", "size": [0.12, 0.84, 0.12], "at": [dx, 0.42, dz], "material": post} for dx in (-1.35, 1.35) for dz in (-0.45, 0.45)]
    shapes += [{"shape": "box", "size": [0.14, h, 0.14], "at": [dx, h / 2, dz], "material": post} for dx in (-1.45, 1.45) for dz, h in ((-0.75, 2.6), (0.75, 2.0))]
    shapes.append({"shape": "box", "size": [3.3, 0.08, 1.9], "at": [0, 2.35, 0], "rot": [18.3, 0, 0],
                   "material": {"texture": "stripes", "color": ctx["params"]["color"], "color2": ctx["params"]["color2"]}})
    return {"shapes": shapes,
            "anchors": [{"id": "counter", "type": "surface", "tags": ["stall", "counter"], "at": [0, 0.97, -0.1], "extent": [2.6, 0.9]},
                        {"id": "front", "type": "ground", "tags": ["outside", "stall"], "at": [0, 0, 1.4], "extent": [3.0, 0.8]}]}
