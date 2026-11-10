# A heap of scrap: fourteen tumbled lumps of rusted metal, timber and tin, worth digging through.
import random

RUST = ["#7a5a3a", "#8f6f4f", "#5f6e7a", "#b85c38", "#6a6a62"]


def on_build(ctx):
    r = random.Random(ctx["seed"])
    shapes = []
    for i in range(14):
        shapes.append({"shape": "box", "size": [round(0.3 + r.random() * 0.9, 2), round(0.2 + r.random() * 0.6, 2), round(0.3 + r.random() * 0.9, 2)],
                       "at": [round((r.random() - 0.5) * 3, 2), round(0.2 + r.random() * 0.9, 2), round((r.random() - 0.5) * 2.4, 2)],
                       "rot": [round(r.random() * 57, 1), round(r.random() * 172, 1), round(r.random() * 57, 1)],
                       "material": {"color": RUST[i % 5], "metal": 0.3, "rough": 0.8}})
    shapes.append({"shape": "box", "size": [3.4, 1.6, 2.6], "at": [0, 0.8, 0], "hitbox": True,
                   "tip": {"title": "A heap of scrap", "text": "Worth digging through, if you know what you're after."}})
    return {"shapes": shapes, "anchors": [{"id": "foot", "type": "ground", "tags": ["outside", "heap"], "at": [0, 0, 1.8], "extent": [3.0, 0.8]}]}
