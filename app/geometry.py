"""The shape vocabulary parts and layouts are drawn in (docs/DESIGN-modules.md, "Parts and layouts").

A part's `on_build` returns plain data: shapes (box, plane, cylinder, cone, sphere, ico, dodeca, gable, sprite, light), each with a position,
a rotation in degrees, and a material named after one of the generated textures; and anchors. Nothing here draws; this checks what a module
returns (every refusal says what to fix) and moves a part into place in a layout. The browser's layout renderer (web/world/layout.js)
turns the same data into three.js, so a new place needs no new browser code.
"""
import math
import re

SHAPES = ("box", "plane", "cylinder", "cone", "sphere", "ico", "dodeca", "gable", "sprite", "light")
TEXTURES = ("grass", "soil", "cliff", "plaster", "inner", "thatch", "planks", "floor", "stone", "cobble", "leaves", "water", "door", "window",
            "whitewash", "slate", "shingles", "marsh", "mud", "pebbles", "sea", "drawers", "brick", "tiles", "books", "sand", "heather", "stripes")
ARTS = ("reed", "flower", "curlew", "spark", "coin")       # small sprites the browser already draws
HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
SHAPES_MAX, ANCHORS_MAX, REACH, SIZE_MAX = 400, 24, 60.0, 60.0
ANCHOR_TYPES = ("wall", "surface", "floor", "ground", "hang")
ANIMATIONS = ("flow", "tide")


class Bad(ValueError):
    """Geometry that can't be drawn; the message says which shape and what to fix."""


def _num(v, what: str, lo: float = -REACH, hi: float = REACH) -> float:
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or not lo <= v <= hi:
        raise Bad(f"{what} is a number from {lo:g} to {hi:g}")
    return float(v)


def _vec(v, what: str, n: int = 3, lo: float = -REACH, hi: float = REACH) -> list[float]:
    if not isinstance(v, (list, tuple)) or len(v) != n:
        raise Bad(f"{what} is a list of {n} numbers")
    return [_num(x, what, lo, hi) for x in v]


def _hex(v, what: str) -> str:
    if not isinstance(v, str) or not HEX.match(v):
        raise Bad(f"{what} is a colour like \"#3a2a1c\"")
    return v.lower()


def material(m, what: str) -> dict:
    """{"texture": name, "repeat": [u, v], "color": hex (planks, leaves, stripes' first), "color2": hex (stripes), "metal", "rough", "emissive",
    "lamp": true (lit at night), "double": true, "opacity"}; or just {"color": hex}."""
    if not isinstance(m, dict):
        raise Bad(f"{what}: `material` is an object, like {{\"texture\": \"planks\", \"repeat\": [2, 1]}}")
    out = {}
    if "texture" in m:
        if m["texture"] not in TEXTURES:
            raise Bad(f"{what}: texture is one of {', '.join(TEXTURES)}")
        out["texture"] = m["texture"]
        out["repeat"] = _vec(m.get("repeat", [1, 1]), f"{what}: repeat", 2, 0.1, 40)
    elif "color" not in m:
        raise Bad(f"{what}: a material needs a texture or a color")
    for key in ("color", "color2", "emissive"):
        if key in m:
            out[key] = _hex(m[key], f"{what}: {key}")
    for key, lo, hi in (("metal", 0, 1), ("rough", 0, 1), ("opacity", 0.1, 1)):
        if key in m:
            out[key] = _num(m[key], f"{what}: {key}", lo, hi)
    for key in ("lamp", "double"):
        if m.get(key):
            out[key] = True
    return out


def shape(s, i: int) -> dict:
    """One shape, checked and normalised."""
    what = f"shape {i}"
    if not isinstance(s, dict) or s.get("shape") not in SHAPES:
        raise Bad(f"{what}: `shape` is one of {', '.join(SHAPES)}")
    kind = s["shape"]
    what = f"shape {i} ({kind})"
    out = {"shape": kind, "at": _vec(s.get("at", [0, 0, 0]), f"{what}: at")}
    if "rot" in s:
        out["rot"] = _vec(s["rot"], f"{what}: rot (degrees)", 3, -360, 360)
    if "scale" in s:
        out["scale"] = _vec(s["scale"], f"{what}: scale", 3, 0.01, 20)
    if kind == "box":
        out["size"] = _vec(s.get("size"), f"{what}: size [w, h, d]", 3, 0.01, SIZE_MAX)
    elif kind in ("plane", "sprite"):
        out["size"] = _vec(s.get("size"), f"{what}: size [w, h]", 2, 0.01, SIZE_MAX)
    elif kind in ("cylinder", "cone"):
        out["radius"] = _num(s.get("radius"), f"{what}: radius", 0.01, SIZE_MAX)
        out["height"] = _num(s.get("height"), f"{what}: height", 0.01, SIZE_MAX)
        out["segments"] = int(_num(s.get("segments", 10), f"{what}: segments", 3, 32))
        if kind == "cylinder":
            out["top"] = _num(s.get("top", out["radius"]), f"{what}: top (radius)", 0, SIZE_MAX)
    elif kind in ("sphere", "ico", "dodeca"):
        out["radius"] = _num(s.get("radius"), f"{what}: radius", 0.01, SIZE_MAX)
        if kind == "sphere":
            out["segments"] = int(_num(s.get("segments", 8), f"{what}: segments", 3, 24))
    elif kind == "gable":
        out["width"] = _num(s.get("width"), f"{what}: width", 0.01, SIZE_MAX)
        out["height"] = _num(s.get("height"), f"{what}: height", 0.01, SIZE_MAX)
    if kind == "sprite":
        if s.get("art") in ARTS:
            out["art"] = s["art"]
        elif isinstance(s.get("pixels"), dict):
            from . import art
            try:
                rows, palette = art.clean_pixels(s["pixels"].get("rows"), s["pixels"].get("palette"))
            except art.SvgRejected as e:
                raise Bad(f"{what}: {e}") from None
            out["pixels"] = {"rows": rows, "palette": palette}
        else:
            raise Bad(f"{what}: a sprite has `pixels` ({{rows, palette}}) or `art` (one of {', '.join(ARTS)})")
    elif kind == "light":
        out["color"] = _hex(s.get("color", "#ffc070"), f"{what}: color")
        out["strength"] = _num(s.get("strength", 1), f"{what}: strength", 0, 3)
        out["range"] = _num(s.get("range", 8), f"{what}: range", 0.5, 40)
        if s.get("lamp"):
            out["lamp"] = True
    elif s.get("hitbox"):
        out["material"] = {"color": "#000000"}
    else:
        if "faces" in s:                                     # a box's top and sides, like a block of ground: {"top": m, "side": m}
            faces = s["faces"]
            if kind != "box" or not isinstance(faces, dict) or set(faces) != {"top", "side"}:
                raise Bad(f"{what}: `faces` is for a box: {{\"top\": material, \"side\": material}}")
            out["faces"] = {k: material(v, f"{what}: {k}") for k, v in faces.items()}
        else:
            out["material"] = material(s.get("material"), what)
    if s.get("sway"):
        out["sway"] = True
    if "animate" in s:                                       # water that flows (its texture drifts) or rises and falls with the tide
        if s["animate"] not in ANIMATIONS or kind in ("light", "sprite"):
            raise Bad(f"{what}: `animate` is one of {', '.join(ANIMATIONS)}")
        out["animate"] = s["animate"]
        out["speed"] = _num(s.get("speed", 0.02), f"{what}: speed", 0, 1)
    if s.get("hitbox"):                                      # drawn invisibly: only there to carry a tip
        if kind != "box" or "tip" not in s:
            raise Bad(f"{what}: a `hitbox` is an invisible box with a `tip`")
        out["hitbox"] = True
    if s.get("shadow") is False:
        out["shadow"] = False
    tip = s.get("tip")
    if tip is not None:
        if not isinstance(tip, dict) or not isinstance(tip.get("title", ""), str) or not isinstance(tip.get("text", ""), str):
            raise Bad(f"{what}: `tip` is {{title, text}}")
        out["tip"] = {"title": tip.get("title", "")[:60], "text": tip.get("text", "")[:200]}
    return out


def anchor(a, i: int) -> dict:
    what = f"anchor {i}"
    if not isinstance(a, dict) or not isinstance(a.get("id"), str) or not re.match(r"^[a-z0-9][a-z0-9-]{0,39}$", a["id"]):
        raise Bad(f"{what}: `id` is lowercase letters, digits and dashes")
    if a.get("type") not in ANCHOR_TYPES:
        raise Bad(f"{what}: `type` is one of {', '.join(ANCHOR_TYPES)}")
    tags = a.get("tags") or []
    if not isinstance(tags, list) or not 1 <= len(tags) <= 6 or not all(isinstance(t, str) and t for t in tags):
        raise Bad(f"{what}: `tags` is a list of 1 to 6 words")
    normal = [0.0, 1.0, 0.0] if a["type"] != "wall" else _vec(a.get("normal", [0, 0, 1]), f"{what}: normal", 3, -1, 1)
    return {"id": a["id"], "type": a["type"], "tags": [t.strip().lower()[:24] for t in tags], "at": _vec(a.get("at"), f"{what}: at"),
            "normal": normal, "extent": _vec(a.get("extent", [1.0, 1.0] if a["type"] == "wall" else [2.0, 1.0]),
                                             f"{what}: extent [width, height or depth]", 2, 0.05, SIZE_MAX)}


def built(result) -> dict:
    """What a part's on_build returned: {"shapes": [...], "anchors": [...]}, checked."""
    if not isinstance(result, dict) or not isinstance(result.get("shapes"), list):
        raise Bad("on_build returns {\"shapes\": [...], \"anchors\": [...]}")
    shapes, anchors = result["shapes"], result.get("anchors") or []
    if not shapes or len(shapes) > SHAPES_MAX:
        raise Bad(f"a part has 1 to {SHAPES_MAX} shapes")
    if not isinstance(anchors, list) or len(anchors) > ANCHORS_MAX:
        raise Bad(f"a part has at most {ANCHORS_MAX} anchors")
    out = {"shapes": [shape(s, i) for i, s in enumerate(shapes)], "anchors": [anchor(a, i) for i, a in enumerate(anchors)]}
    ids = [a["id"] for a in out["anchors"]]
    if len(ids) != len(set(ids)):
        raise Bad("each anchor needs its own id")
    return out


# --- moving a part into place ------------------------------------------------------------------------------------------------
def _turn(x: float, z: float, deg: float) -> tuple[float, float]:
    """Rotate a point about the vertical axis (degrees, counter-clockwise seen from above, as three.js turns about +y)."""
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return x * c + z * s, -x * s + z * c


def place(part: dict, at, turn: float, role: str) -> dict:
    """A built part moved to `at` and turned `turn` degrees about the vertical; its anchors' ids are prefixed and tagged with the role."""
    ax, ay, az = at
    shapes = []
    for s in part["shapes"]:
        x, y, z = s["at"]
        x, z = _turn(x, z, turn)
        rot = list(s.get("rot", [0.0, 0.0, 0.0]))
        rot[1] = rot[1] + turn
        shapes.append({**s, "at": [round(x + ax, 4), round(y + ay, 4), round(z + az, 4)], "rot": [round(v, 4) for v in rot]})
    anchors = []
    for a in part["anchors"]:
        x, y, z = a["at"]
        x, z = _turn(x, z, turn)
        nx, nz = _turn(a["normal"][0], a["normal"][2], turn)
        anchors.append({**a, "id": f"{role}-{a['id']}", "tags": list(dict.fromkeys(a["tags"] + [role])),
                        "at": [round(x + ax, 4), round(y + ay, 4), round(z + az, 4)], "normal": [round(nx, 4), a["normal"][1], round(nz, 4)]})
    return {"shapes": shapes, "anchors": anchors}
