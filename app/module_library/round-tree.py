# A round, leafy tree: a trunk and four clumps of leaves that sway, in the season's colours. Its shade is ground to put things in.
CLUMPS = [[0, 2.4, 0, 1.5], [0.8, 2.0, 0.3, 1.0], [-0.8, 2.1, -0.2, 1.1], [0.2, 3.1, -0.3, 1.0]]


def on_build(ctx):
    s = float(ctx["params"]["scale"])
    trunk = {"shape": "box", "size": [0.5 * s, 1.6 * s, 0.5 * s], "at": [0, 0.8 * s, 0],
             "material": {"texture": "planks", "repeat": [1, 2], "color": "#5a3d27"}}
    leaves = [{"shape": "ico", "radius": r * s, "at": [dx * s, dy * s, dz * s], "material": {"texture": "leaves", "repeat": [2, 2]}, "sway": True}
              for dx, dy, dz, r in CLUMPS]
    return {"shapes": [trunk] + leaves,
            "anchors": [{"id": "shade", "type": "ground", "tags": ["outside", "shade"], "at": [0, 0, 1.3 * s], "extent": [1.6 * s, 0.6]}]}
