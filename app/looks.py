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


def _pick(name: str, field: str) -> str:
    opts = LOOK[field]
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
