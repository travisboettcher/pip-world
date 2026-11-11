A module is one Python file (plain Python; you may import math, random, json, re, datetime, itertools, functools, collections,
statistics, heapq, bisect; nothing else, no files, no network, no attributes starting with "_", no .format). Define any of:
- on_install(ctx): once, when it goes live. on_time(ctx): at the time it asked for with "schedule". on_event(ctx): when one of the
  event kinds you list happens (ctx["event"] = {"kind", "data"}). on_tick(ctx): every few minutes (costly: prefer on_time).
  on_message(ctx): Pip said something to one of your voices (ctx["message"] = {to, text}). on_answer(ctx): the model's words for an
  "ask" (ctx["answer"] = {purpose, text}; text is "" if none came).
Each gets ctx and returns a dict (or nothing). ctx holds:
- now (seconds since the epoch, local clock), seed (for random.Random(ctx["seed"])), state (the dict you returned last time as "state").
- time: {hour, minute, weekday ("Monday"...), season}. weather: {condition, temp, unit, daylight} or None.
- pip: {where (a place key; Pip's own home is "workshop"), at_home, activity, asleep, walking, hunger, energy (0 to 1), mood, coins}. items: Pip's
  belongings [{name, qty, kind}]. garden: the plots [{plot, crop, state ("empty", "growing", "ready"), ready_in_min}]. visitors:
  {waiting} (how many visitors' messages wait for Pip).
- places: the real places [{key, label, kind}] (kinds: home, wild, yard, sight, library, neighbor, shop, market).
- works: Pip's newest pixel drawings [{id, title, subject, rows, palette}]. stalls: Pip's stall lines [{place, item, kind, qty, ask,
  fair (the going price), sold_today, selling (Pip is there and it is open)}].
- facts: what other modules published, by module name. people: who lives in Pip's world [{name, kind}]. creations: Pip's things
  [{name, running, tended}]. happenings: {recent: [{category, tone, severity, ts, status}], today, room ("" when one can happen now,
  else why not), can_remember}.
Return any of:
- "state": a dict to keep. "publish": facts other modules may read. "schedule": when to call on_time next (a time, like ctx["now"] + 3600).
- "perceive": one line Pip will notice (rare: a few a day at most). "log": one line for the day's record. "wake": true to wake Pip (rarer).
- "voices": someone or something Pip can talk to, that your code speaks for: [{"name": "the Ferryman", "at": a place's key or "home",
  "about": "who Pip sees"}] (up to 4; never a name already in the world). Pip talks to them with say(to=...) when it is there; you hear
  it in on_message. ctx["voices"] holds yours. "speak": {"as": one of your voices, "text": a line, "to_pip": true when it answers Pip
  (that wakes Pip)}. "ask": {"prompt": what to write and who is speaking (you keep the conversation in your state), "purpose": a word,
  "most": characters (up to 600)}: the model's words come back later to on_answer; ctx["asking"] is how many are still waiting (3 at
  most). A dozen asks and two dozen lines a day.
- "happen": something happens to Pip (twice a day at most): {"category": a word or two ("fog", "lost cat"), "tone": "good" | "bad" |
  "neutral", "severity": "minor" | "medium" | "major", "effects": up to 2 of {"kind": "coins"} (found, or lost), {"kind": "item",
  "name"?: something found in this world, "gift"?: true}, {"kind": "food_loss"}, {"kind": "crop", "plot": n, "how": "time" | "yield" |
  "ruin"}, {"kind": "energy"}, {"kind": "hunger"}, {"kind": "price", "place": a place that sells, "item"?}, {"kind": "stop", "creation":
  one of Pip's things that need tending}, {"kind": "news", "name": a neighbor}, {"kind": "memory"} (an old thought of Pip's comes back),
  "about": what happened, in a line (the writer keeps to it), "names": who or what it may mention}. You say what kind of thing changes;
  the world decides how much, by the severity. A good turn only gives, a bad one only takes, a neutral one changes nothing. It is written
  later; one that no longer fits is dropped. Only when ctx["happenings"]["room"] is "".
- "show": up to 8 pixel pictures in scenes: [{"id": "bell", "sprite": {"rows": ["..kk..", ...], "palette": {"k": "#3a2a1c"}},
  "size": 0.6, "frame": false, "at": {"type": "wall"|"surface"|"floor"|"ground", "place": "home" or a place key, "tags": [...]},
  "motion": "bob"|"sway"|"spin", "tip": {"title": "...", "text": "..."}}]. Rows are 4 to 32 letters long, all the same length, 4 to 32
  rows; "." is empty; each letter is a colour in the palette. "place" is "home" (Pip's workshop) or a place's key. Ask only for anchors
  that exist; tags must all match (leave them out to take any of that type). A "show" stays until you send another; [] clears it.
  The anchors, by kind of place:
ANCHORS
Event kinds you can listen for: EVENT_KINDS.
An example, only to show how the pieces fit (it is not an idea to propose; think of your own):

    def _next(ctx):
        return ctx["now"] + 3600 - ctx["now"] % 3600

    def on_install(ctx):
        return {"schedule": _next(ctx)}

    def on_time(ctx):
        out = {"schedule": _next(ctx)}
        t = ctx["time"]
        if t["weekday"] == "Saturday" and t["hour"] == 9:
            out["log"] = "The bell in the square rings for market day."
            if ctx["pip"]["where"] == "Brygdon":                 # a place's key, from ctx["places"]
                out["perceive"] = "The bell in the square rings: the market is open."
        return out

A new place (instead of a rule, and rarely): somewhere people here would talk about and walk to, a mill, a ford, a ruin, a small
shop. Report module "place", with label (its name as people say it), place_kind (one of PLACE_KINDS), description (what it is like, a
few sentences), distance (near or far), items (up to 6 things that can be found or had there), setting (one of SETTINGS), opens and
closes (hours, for a shop or market), and code whose on_build(ctx) lays it out. ctx holds season and seed (for random.Random(ctx["seed"])).
It returns {"parts": [{"part": a part's name, "params": {...}, "at": [x, 0, z], "turn": degrees, "role": "a-word"}], "shapes": [...],
"anchors": [...]}. The camera looks from the front: z grows towards the viewer; keep things within x -14 to 14 and z -16 to 4, with
open ground in front. Give the ground as a box, like {"shape": "box", "size": [30, 2, 16], "at": [0, -1, -4], "faces": {"top":
{"texture": "grass", "repeat": [15, 8]}, "side": {"texture": "cliff", "repeat": [15, 1]}}, "tip": {"title": "$label", "text":
"$description"}}: its top is at y 0, so anything lying on it (a stream, a path, a pond) sits a little above, at y 0.02, and anything
standing on it has its base at y 0. Add ground anchors tagged "pip" (where Pip stands, near z 0), "finds" (where things lie) and "people",
like {"id": "pip", "type": "ground", "tags": ["outside", "pip"], "at": [0, 0, 0], "extent": [8, 2]} (extent: width along x, depth along z).
A shop or market also needs a counter: a box to stand at, and a surface anchor tagged "counter" on top of it (its goods are set out there
and the keeper stands just behind), inside the building if there is one. Add "reserved" to the tags of the anchors the scene itself
draws on (pip, people, counter), so things modules show stay off them.
Shapes: box (size), plane (size), cylinder (radius, top, height), cone, sphere, ico, dodeca, torus (radius, tube), gable (width, height),
sprite (pixels or art), light (color, strength, range, lamp); each with at, rot (degrees), and a material {texture, repeat, color}; textures:
TEXTURES. A shape (or a part entry) with "when": [...] shows only while all of those hold: CONDITIONS.
The parts you can use:
PARTS
When Pip first gets there, it is as you described it; until someone tells Pip about it, nobody knows it is there.
