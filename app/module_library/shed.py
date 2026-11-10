# A plank shed with a shingled roof, a little tilted.
def on_build(ctx):
    return {"shapes": [{"shape": "box", "size": [3, 2.4, 2.4], "at": [0, 1.2, 0], "material": {"texture": "planks", "repeat": [2, 2], "color": "#5a4a3a"}},
                       {"shape": "box", "size": [3.6, 0.2, 2.8], "at": [0, 2.6, 0], "rot": [8.6, 0, 0], "material": {"texture": "shingles", "repeat": [2, 2]}}]}
