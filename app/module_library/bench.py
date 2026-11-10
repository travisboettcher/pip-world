# A wooden bench, to sit and look from. Its seat is where Pip sits.
def on_build(ctx):
    wood = {"texture": "planks", "repeat": [2, 1], "color": "#7a5236"}
    return {"shapes": [{"shape": "box", "size": [2.2, 0.12, 0.6], "at": [0, 0.5, 0], "material": wood},
                       {"shape": "box", "size": [0.12, 0.5, 0.5], "at": [-0.9, 0.25, 0], "material": wood},
                       {"shape": "box", "size": [0.12, 0.5, 0.5], "at": [0.9, 0.25, 0], "material": wood},
                       {"shape": "box", "size": [2.2, 0.8, 0.8], "at": [0, 0.4, 0], "hitbox": True, "tip": {"title": "A bench", "text": "To sit and look from."}}],
            "anchors": [{"id": "seat", "type": "surface", "tags": ["seat"], "at": [0, 0.56, 0], "extent": [2.0, 0.5]}]}
