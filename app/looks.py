"""How characters look, and what a place shows, in the world view (docs/DESIGN-world-view.md).

A character's look is chosen once from fixed lists, so the browser's sprite generator can draw it: the GM picks from the lists for who they are
(`gm.invent_look`), and if that fails the engine picks from words in their persona and a hash of their name. Props are a fixed vocabulary
of things a scene can draw, found in a record's own words; only the prop names leave the engine, never the text they were found in.
"""
import re
import zlib

LOOK = {
    "height": ("short", "medium", "tall"),
    "hair": ("white", "grey", "black", "brown", "auburn", "fair", "none"),
    "skin": ("pale", "light", "olive", "brown", "dark"),
    "top": ("grey", "brown", "green", "blue", "red", "ochre", "plum", "cream"),
    "bottom": ("grey", "brown", "green", "blue", "navy", "black"),
    "accessory": ("shawl", "apron", "hat", "glasses", "satchel", "scarf", "none"),
}
HINTS = {                                           # words in a persona that settle a feature, before any hashing
    "height": {"tall": "tall", "lanky": "tall", "short": "short", "small": "short", "little": "short", "stout": "short"},
    "hair": {"white-haired": "white", "white hair": "white", "grey-haired": "grey", "grey hair": "grey", "silver": "grey", "bald": "none",
             "red-haired": "auburn", "auburn": "auburn", "fair-haired": "fair", "blond": "fair", "dark-haired": "black", "widow": "white", "old": "grey"},
    "accessory": {"shawl": "shawl", "apron": "apron", "hat": "hat", "spectacles": "glasses", "glasses": "glasses", "eyesight": "glasses",
                  "satchel": "satchel", "scarf": "scarf", "baker": "apron", "smith": "apron", "keeper": "shawl"},
}
PROPS = {                                           # prop -> words that bring it into a scene
    "lighthouse": ("lighthouse",), "tide chart": ("tide", "tides"), "sea glass": ("sea glass",), "driftwood": ("driftwood",),
    "nets": ("net", "nets", "fishing"), "boats": ("boat", "boats", "harbour", "harbor", "quay"), "rope": ("rope", "ropes"),
    "lanterns": ("lantern", "lanterns"), "drawers": ("drawer", "drawers"), "beehives": ("bee", "bees", "hive", "hives", "honey"),
    "loom": ("loom", "weaver", "weaving", "wool"), "books": ("book", "books", "ledger", "log"), "tin": ("tin",),
    "barrow": ("barrow", "barrows", "cart"), "crates": ("crate", "crates"), "bunting": ("bunting", "flags", "awning", "awnings"),
    "well": ("well",), "kiln": ("kiln", "pottery", "potter"), "anvil": ("anvil", "forge", "smith"), "herbs": ("herb", "herbs"),
    "vegetables": ("vegetable", "vegetables", "carrot", "carrots", "cabbage"), "birds": ("curlew", "gull", "gulls", "birds", "heron"),
    "shingle": ("shingle",), "reeds": ("reed", "reeds", "marsh"), "tools": ("tool", "tools", "file", "hammer", "wire"),
}


def _pick(name: str, field: str, lists: dict | None = None) -> str:
    opts = (lists or LOOK)[field]
    return opts[zlib.crc32(f"{name}|{field}".encode()) % len(opts)]


def fallback(name: str, persona: str) -> dict:
    """A look from words in the persona where they settle it, otherwise from the name."""
    text = (persona or "").lower()
    out = {}
    for field in LOOK:
        hit = next((v for k, v in HINTS.get(field, {}).items() if re.search(rf"\b{re.escape(k)}\b", text)), None)
        out[field] = hit or _pick(name, field)
    return out


def clean(raw, name: str, persona: str) -> dict:
    """The GM's choices where they are on the lists; anything else falls back."""
    base = fallback(name, persona)
    if not isinstance(raw, dict):
        return base
    return {f: (str(raw.get(f)).strip().lower() if str(raw.get(f) or "").strip().lower() in opts else base[f]) for f, opts in LOOK.items()}


def props(*texts) -> list[str]:
    """The props a scene may draw, found in these texts (whole words), in the vocabulary's order."""
    text = " ".join(str(t or "") for t in texts).lower()
    return [p for p, words in PROPS.items() if any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)]


async def ensure(state, settings, gm, now: float) -> None:
    """Give every in-person character without a look one, once (from the GM; from the fallback if the GM fails twice)."""
    if settings.character_looks != "on":
        return
    for ch in state.characters():
        if ch["kind"] not in ("neighbor", "resident") or ch.get("look"):
            continue
        tries = int(state.meta(f"look_tries:{ch['id']}") or 0)
        raw = await gm.invent_look(ch["name"], ch["persona"], ch["about"]) if gm and tries < 2 else None
        if raw is None and tries < 2:
            state.set_meta(**{f"look_tries:{ch['id']}": str(tries + 1)})
            continue
        state.update_character(ch["id"], look=clean(raw, ch["name"], ch["persona"]))


# --- a place's scene details (step 4): walls, roof, palette, setting and props, chosen once from fixed lists ---------------------------
SCENE = {
    "walls": ("plaster", "whitewash", "stone", "brick", "planks"),
    "roof": ("thatch", "slate", "shingle", "tile"),
    "palette": ("warm", "cool", "earth", "moss", "rose", "sand", "slate", "honey"),
    "setting": ("wood", "heath", "shore", "marsh", "hills", "riverside", "town", "field"),
}
SCENE_PROPS_MAX = 4
SETTING_WORDS = {"wood": ("wood", "woods", "forest", "trees", "copse", "grove"), "shore": ("shore", "beach", "sea", "coast", "cove", "harbour", "harbor", "quay"),
                 "marsh": ("marsh", "reeds", "fen", "mudflats", "bog"), "hills": ("hill", "hills", "quarry", "crag", "ridge", "tor"),
                 "riverside": ("river", "stream", "brook", "ford", "mill"), "heath": ("heath", "moor", "heather", "gorse"),
                 "town": ("square", "street", "town", "village", "shop"), "field": ("field", "meadow", "orchard", "farm", "pasture")}
KIND_SETTING = {"market": "town", "shop": "town", "yard": "hills", "wild": "wood", "sight": "hills", "library": "town", "home": "field", "neighbor": "field"}


def fallback_scene(key: str, kind: str, text: str) -> dict:
    """Scene details from the place's own words where they say, its kind, and a hash of its name."""
    t = (text or "").lower()
    has = lambda w: re.search(rf"\b{re.escape(w)}\b", t)
    setting = next((s for s, words in SETTING_WORDS.items() if any(has(w) for w in words)), KIND_SETTING.get(kind, "field"))
    walls = next((w for w in ("stone", "brick", "whitewash", "planks") if has(w) or (w == "planks" and has("timber"))), _pick(key, "walls", SCENE))
    roof = next((r for r in ("thatch", "slate", "tile") if has(r) or has(r + "d")), _pick(key, "roof", SCENE))
    return {"walls": walls, "roof": roof, "palette": _pick(key, "palette", SCENE), "setting": setting, "props": props(text)[:SCENE_PROPS_MAX]}


def clean_scene(raw, key: str, kind: str, text: str) -> dict:
    base = fallback_scene(key, kind, text)
    if not isinstance(raw, dict):
        return base
    out = {f: (str(raw.get(f)).strip().lower() if str(raw.get(f) or "").strip().lower() in opts else base[f]) for f, opts in SCENE.items()}
    picked = [p for p in (raw.get("props") if isinstance(raw.get("props"), list) else []) if isinstance(p, str) and p.strip().lower() in PROPS]
    out["props"] = list(dict.fromkeys([p.strip().lower() for p in picked] + base["props"]))[:SCENE_PROPS_MAX]
    return out


def place_scene(state, key: str, kind: str, text: str) -> dict:
    """A place's scene details: the ones chosen and kept, or the fallback until they are."""
    import json
    kept = state.meta(f"scene:{key}")
    return json.loads(kept) if kept else fallback_scene(key, kind, text)


async def ensure_scenes(state, settings, gm, library, now: float) -> None:
    """Choose scene details once for every real place that has none (the GM picks from the lists; two failures and the fallback is kept)."""
    import json
    from . import worldmap
    if settings.place_scenes != "on":
        return
    snap = worldmap.snapshot(state, settings, library, now)
    for p in snap["places"]:
        if p["heard_only"] or state.meta(f"scene:{p['key']}"):
            continue
        text = place_text(state, p["key"])
        tries = int(state.meta(f"scene_tries:{p['key']}") or 0)
        raw = await gm.invent_scene(p["label"], p["kind"], text) if gm and tries < 2 else None
        if raw is None and tries < 2:
            state.set_meta(**{f"scene_tries:{p['key']}": str(tries + 1)})
            continue
        state.set_meta(**{f"scene:{p['key']}": json.dumps(clean_scene(raw, p["key"], p["kind"], text))})


def place_text(state, key: str) -> str:
    """Everything known about a place, for picking its look: its record, or whoever lives there."""
    from . import places
    rec = state.place_row(key)
    if rec:
        return " ".join([rec.get("description") or "", rec.get("blurb") or "", *[m.get("there", "") for m in rec.get("mentions") or []]])
    ch = places.neighbor_at(state, key)
    if ch:
        return " ".join([ch["about"], ch["persona"], " ".join(ch["told"]), " ".join(w["name"] for w in ch.get("wares") or [])])
    return {"library": "a library of tall shelves", "woods": "a wood of trees past the garden", "junkyard": "a scrapyard over the hill",
            places.HOME: "a workshop with a small garden"}.get(key, "")
