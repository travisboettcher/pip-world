# A pine: a thin trunk and three cones, dark green, darker and greyer in winter.
TIERS = [[1.4, 1.6], [1.1, 2.5], [0.75, 3.3]]


def on_build(ctx):
    s = float(ctx["params"]["scale"])
    green = "#3f5a46" if ctx["season"] == "winter" else "#2f6a3a"
    trunk = {"shape": "box", "size": [0.3 * s, s, 0.3 * s], "at": [0, 0.5 * s, 0], "material": {"texture": "planks", "repeat": [1, 2], "color": "#5a3d27"}}
    tiers = [{"shape": "cone", "radius": r * s, "height": 1.4 * s, "segments": 7, "at": [0, h * s, 0],
              "material": {"texture": "leaves", "repeat": [2, 2], "color": green}} for r, h in TIERS]
    return {"shapes": [trunk] + tiers}
