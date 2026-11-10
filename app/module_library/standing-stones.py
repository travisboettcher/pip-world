# Old standing stones with a lintel across them: something to walk out and see.
SPOTS = [[-3, 0.2], [-1, -0.4], [1.2, -0.2], [3.2, 0.4]]


def on_build(ctx):
    stone = {"texture": "stone", "repeat": [2, 2]}
    shapes = [{"shape": "box", "size": [0.9, 2.4 + (i % 2) * 0.8, 0.7], "at": [x, 1.2 + (i % 2) * 0.4, z], "material": stone} for i, (x, z) in enumerate(SPOTS)]
    shapes.append({"shape": "box", "size": [5.2, 0.6, 0.8], "at": [0.1, 3.4, -0.1], "material": stone})
    shapes.append({"shape": "box", "size": [7, 4, 1.5], "at": [0, 1.8, 0], "hitbox": True, "tip": {"title": "The old stones", "text": "Something to walk out and see."}})
    return {"shapes": shapes}
