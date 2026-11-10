# A whitewashed lighthouse whose lamp comes on at dusk.
def on_build(ctx):
    return {"shapes": [{"shape": "cylinder", "radius": 1.15, "top": 0.85, "height": 7, "segments": 10, "at": [0, 3.5, 0],
                        "material": {"texture": "whitewash", "repeat": [3, 4]}, "tip": {"title": "The lighthouse", "text": "It stands over the water."}},
                       {"shape": "cylinder", "radius": 0.7, "height": 0.9, "segments": 10, "at": [0, 7.4, 0],
                        "material": {"color": "#444036", "emissive": "#fff0b0", "lamp": True}}]}
