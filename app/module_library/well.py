# A stone well with two posts and a little thatched roof: where people stop to talk.
def on_build(ctx):
    post = {"texture": "planks", "repeat": [1, 2], "color": "#6b4a30"}
    shapes = [{"shape": "cylinder", "radius": 0.95, "top": 0.9, "height": 0.9, "segments": 12, "at": [0, 0.45, 0],
               "material": {"texture": "stone", "repeat": [3, 1]}, "tip": {"title": "The well", "text": "Where people stop to talk."}},
              {"shape": "box", "size": [0.14, 1.8, 0.14], "at": [-0.75, 1.3, 0], "material": post},
              {"shape": "box", "size": [0.14, 1.8, 0.14], "at": [0.75, 1.3, 0], "material": post},
              {"shape": "box", "size": [2.0, 0.12, 1.4], "at": [0, 2.3, 0], "material": {"texture": "thatch", "repeat": [2, 1]}}]
    return {"shapes": shapes,
            "anchors": [{"id": "rim", "type": "surface", "tags": ["well", "rim"], "at": [0, 0.9, 0.6], "extent": [1.2, 0.3]},
                        {"id": "side", "type": "ground", "tags": ["outside", "well"], "at": [0, 0, 1.6], "extent": [2.0, 0.8]}]}
