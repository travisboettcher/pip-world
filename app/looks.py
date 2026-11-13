"""How characters look, and what a place shows, in the world view (docs/DESIGN-world-view.md).

A character's look is chosen once from fixed lists (the world pack's scene.json), so the browser's sprite generator can draw it: the GM picks from the lists for who they are
(`gm.invent_look`), and if that fails the engine picks from words in their persona and a hash of their name. Props are a fixed vocabulary
of things a scene can draw, found in a record's own words; only the prop names leave the engine, never the text they were found in.
"""
import re
import zlib

from . import world_pack



def vocab() -> dict:
    """The world's scene vocabulary (its pack's scene.json): looks and their hints, props and their words, scene details, settings."""
    return world_pack.active().data("scene")


def look_lists() -> dict:
    return vocab().get("look", {})


def prop_words() -> dict:
    return vocab().get("props", {})


def scene_lists() -> dict:
    return vocab().get("scene", {})


def scene_props_max() -> int:
    return vocab().get("scene_props_max", 4)


def _pick(name: str, field: str, lists: dict | None = None) -> str:
    opts = (lists or look_lists())[field]
    return opts[zlib.crc32(f"{name}|{field}".encode()) % len(opts)]


def fallback(name: str, persona: str) -> dict:
    """A look from words in the persona where they settle it, otherwise from the name."""
    text = (persona or "").lower()
    out = {}
    for field in look_lists():
        hit = next((v for k, v in vocab().get("look_hints", {}).get(field, {}).items() if re.search(rf"\b{re.escape(k)}\b", text)), None)
        out[field] = hit or _pick(name, field)
    return out


def clean(raw, name: str, persona: str) -> dict:
    """The GM's choices where they are on the lists; anything else falls back."""
    base = fallback(name, persona)
    if not isinstance(raw, dict):
        return base
    return {f: (str(raw.get(f)).strip().lower() if str(raw.get(f) or "").strip().lower() in opts else base[f]) for f, opts in look_lists().items()}


def props(*texts) -> list[str]:
    """The props a scene may draw, found in these texts (whole words), in the vocabulary's order."""
    text = " ".join(str(t or "") for t in texts).lower()
    return [p for p, words in prop_words().items() if any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)]


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
def fallback_scene(key: str, kind: str, text: str) -> dict:
    """Scene details from the place's own words where they say, its kind, and a hash of its name."""
    t = (text or "").lower()
    has = lambda w: re.search(rf"\b{re.escape(w)}\b", t)
    v, lists = vocab(), scene_lists()
    setting = next((s for s, words in v.get("setting_words", {}).items() if any(has(w) for w in words)),
                   v.get("kind_setting", {}).get(kind, v.get("default_setting", lists["setting"][0])))
    walls = next((w for w in v.get("match_walls", lists["walls"]) if has(w) or (w == "planks" and has("timber"))), _pick(key, "walls", lists))
    roof = next((r for r in v.get("match_roofs", lists["roof"]) if has(r) or has(r + "d")), _pick(key, "roof", lists))
    return {"walls": walls, "roof": roof, "palette": _pick(key, "palette", lists), "setting": setting, "props": props(text)[:scene_props_max()]}


def clean_scene(raw, key: str, kind: str, text: str) -> dict:
    base = fallback_scene(key, kind, text)
    if not isinstance(raw, dict):
        return base
    out = {f: (str(raw.get(f)).strip().lower() if str(raw.get(f) or "").strip().lower() in opts else base[f]) for f, opts in scene_lists().items()}
    picked = [p for p in (raw.get("props") if isinstance(raw.get("props"), list) else []) if isinstance(p, str) and p.strip().lower() in prop_words()]
    out["props"] = list(dict.fromkeys([p.strip().lower() for p in picked] + base["props"]))[:scene_props_max()]
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
    from .modules import notes_on
    rec = state.place_row(key)
    if rec:
        return " ".join([rec.get("description") or "", rec.get("blurb") or "", *[m.get("there", "") for m in rec.get("mentions") or []]])
    ch = places.neighbor_at(state, key)
    if ch:
        return " ".join([ch["about"], ch["persona"], " ".join(ch["told"]), " ".join(notes_on(state, ch["name"]))])
    d = world_pack.active().data("places")
    built_in = {p["key"]: p.get("about", "") for p in [d.get("home", {}), d.get("library", {}), *d.get("start", [])] if p.get("key")}
    return built_in.get(key, "")
