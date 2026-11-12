"""New places written as modules (docs/DESIGN-modules.md, step 6: "The builder proposes places").

A place module with `new` in its manifest describes a place that doesn't exist yet: what it's called, which kind of place it is (an
existing kind, so gathering, browsing and trading work as for any place), what is there, how far, what can be found, its setting and its
hours; its `on_build` is its layout (layouts.py). It enters the world the way invented places do (DESIGN-invented-places.md): when the
owner approves it, a character Pip knows mentions it, and it is recorded as heard-of (so the map shows it and `go_to` works); on Pip's
first arrival it becomes real from the module's own description, without asking the GM to invent one.
"""
import random
import re
import time
import zlib

from . import invented_places as invented
from . import place_kinds as kinds
from .text import clip

DISTANCES = ("near", "far")
ITEMS_MAX = 6
LINK = "place_module:"                                  # meta key: a place -> the module that describes it


def check_new(raw, state=None, name: str = "") -> dict:
    """A new place's description in a manifest, checked; raises ValueError with what to fix."""
    from .looks import scene_lists
    SCENE = scene_lists()
    if not isinstance(raw, dict):
        raise ValueError("`new` describes the place: {label, kind, description, distance, items, setting, opens, closes}")
    label = str(raw.get("label") or "").strip().strip(".,;:!").replace("’", "'")
    if not 3 <= len(label) <= 40 or not re.fullmatch(r"[A-Za-z][A-Za-z0-9' .,&-]*", label):
        raise ValueError("`new.label` is the place's name as people say it: 3 to 40 letters (and spaces, digits, apostrophes, dashes)")
    if raw.get("kind") not in kinds.KINDS:
        raise ValueError(f"`new.kind` is one of {', '.join(kinds.KINDS)}")
    description = clip(raw.get("description"), 500)
    if len(description) < 20:
        raise ValueError("`new.description` says what the place is like, in a sentence or three")
    if raw.get("distance", "far") not in DISTANCES:
        raise ValueError("`new.distance` is near or far")
    items = raw.get("items") or []
    if not isinstance(items, list) or len(items) > ITEMS_MAX or not all(isinstance(i, str) and i.strip() for i in items):
        raise ValueError(f"`new.items` is a list of up to {ITEMS_MAX} things that can be found there")
    if raw.get("setting") not in SCENE["setting"]:
        raise ValueError(f"`new.setting` is one of {', '.join(SCENE['setting'])}")
    out = {"label": label, "kind": raw["kind"], "description": description, "distance": raw.get("distance", "far"),
           "items": [clip(i.strip(), 40).lower() for i in items], "setting": raw["setting"]}
    for k in ("opens", "closes"):
        if raw.get(k) is not None:
            if not isinstance(raw[k], int) or isinstance(raw[k], bool) or not 0 <= raw[k] <= 24:
                raise ValueError(f"`new.{k}` is an hour, 0 to 24")
            if kinds.KINDS[raw["kind"]].shop_hours:          # only shops and markets keep hours; anywhere else is open in daylight
                out[k] = raw[k]
    if state is not None and exists(state, label) and state.meta(LINK + invented.key_for(label)) != name:   # a new version of its own place is fine
        raise ValueError(f"there is already a place called {label!r}")
    return out


def exists(state, label: str) -> bool:
    from . import places
    key = invented.key_for(label)
    return bool(invented.find_record(state, label) or state.place_row(key)
                or key.lower() in {k.lower() for k in places.registry(state, state.s, None)} or invented.core(label) in invented.reserved())


def teller(state, key: str) -> str:
    """Who mentions it: one of the characters Pip has met (a neighbor or a resident), the same one for the same place."""
    people = sorted(c["name"] for c in state.characters() if c["kind"] in ("neighbor", "resident"))
    return people[zlib.crc32(key.encode()) % len(people)] if people else "a passing traveller"


def first_sentence(text: str) -> str:
    return clip(re.split(r"(?<=[.!?])\s", text.strip())[0], invented.THERE_CHARS)


def introduce(state, m: dict, now: float | None = None, rng: random.Random | None = None) -> dict | None:
    """A new place module has gone live: someone tells Pip about it, and it is heard-of. Nothing if the place already exists."""
    from .looks import clean_scene
    import json
    new = m["manifest"].get("new")
    if not new:
        return None
    now = now or time.time()
    key = m["manifest"]["place"]
    if state.place_row(key):
        state.set_meta(**{LINK + key: m["name"]})
        return None
    by = teller(state, key)
    there = first_sentence(new["description"])
    band = invented.BANDS[new["distance"]]
    hours = kinds.hours_for(new["kind"], new.get("opens"), new.get("closes"))
    rec = state.add_place(key, invented.core(new["label"]), aliases=[], kind=new["kind"],
                          mentions=[invented._mention(by, {"place": new["label"], "there": there, "items": new["items"]}, now)],
                          created_at=now, heard_at=now, distance=new["distance"],
                          walk_minutes=round((rng or random.Random(zlib.crc32(key.encode()))).uniform(*band)),
                          hours=list(hours) if hours else None, daylight_only=int(not hours))
    state.set_meta(**{LINK + key: m["name"],
                      f"scene:{key}": json.dumps(clean_scene({"setting": new["setting"]}, key, new["kind"], new["description"]))})
    state.log("heard_of_place", place=key, by=by, there=there, distance=new["distance"])
    return rec


def module_for(state, key: str) -> dict | None:
    """The module that describes a place (its newest version that isn't rejected), if one does."""
    name = state.meta(LINK + key)
    rows = [m for m in state.modules() if m["name"] == name and m["status"] not in ("rejected", "proposed", "waiting")] if name else []
    return rows[-1] if rows else None


def design(state, key: str) -> dict | None:
    """What a module place is like, in the form a GM design takes (invented_places.design), so its first arrival needs no GM."""
    m = module_for(state, key)
    new = (m or {}).get("manifest", {}).get("new")
    if not new:
        return None
    raw = {"description": new["description"], "kind": new["kind"], "loot": [{"name": i, "kind": "material"} for i in new["items"]]}
    for k in ("opens", "closes"):
        if k in new:
            raw[k] = new[k]
    return raw
