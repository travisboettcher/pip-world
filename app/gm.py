"""The game master: a separate LLM prompt that writes world content, never rules.

The engine decides outcomes and owns every number; the GM turns engine facts into flavor (narration) and turns
free-form ideas into data from a fixed vocabulary (project plans, creation specs, effects). Callers validate and
clamp everything returned here, and every method has a non-LLM fallback: if the GM fails (budget hit, API error,
unusable output) the world loses flavor, never correctness.

Structured output uses one `report` tool (works on every backend); a JSON object in plain text is accepted too.
"""
import json
import logging
import re

from .llm.base import LLMBackend, ToolSpec
from . import invented_places
from . import place_kinds
from . import world_pack
from .state import State
from .text import clip  # noqa: F401  (re-exported: callers use gm.clip)

log = logging.getLogger("gm")

SYSTEM = world_pack.active().narrator_system()   # Pip's world's narrator; a GameMaster takes its pack's


class GameMaster:
    def __init__(self, backend: LLMBackend, state: State, max_tokens: int = 1024, system: str = SYSTEM, agent: world_pack.Agent | None = None):
        self.backend, self.state, self.max_tokens, self.system = backend, state, max_tokens, system
        self.agent = agent or world_pack.active().agent

    async def ask(self, task: str, properties: dict, required: list[str], purpose: str,
                  system: str | None = None, max_tokens: int | None = None) -> dict | None:
        """One structured call. Returns the report's arguments, or None (caller falls back)."""
        if self.state.budget_exceeded():
            return None
        spec = ToolSpec("report", "Report your answer.", {"type": "object", "properties": properties,
                                                            "required": required})
        try:
            resp = await self.backend.complete(system=system or self.system, messages=[{"role": "user", "content": task}],
                                               tools=[spec], max_tokens=max_tokens or self.max_tokens)
        except Exception as e:
            log.warning("gm %s failed: %s", purpose, e)
            self.state.log("gm_error", purpose=purpose, error=f"{type(e).__name__}: {e}")
            return None
        self.state.add_usage(resp.usage.input_tokens, resp.usage.output_tokens)
        out = next((c.arguments for c in resp.tool_calls if c.name == "report"), None)
        if out is None and resp.text:
            m = re.search(r"\{.*\}", resp.text, re.S)
            try:
                out = json.loads(m.group(0)) if m else None
            except json.JSONDecodeError:
                out = None
        if not isinstance(out, dict) or any(k not in out for k in required):
            self.state.log("gm_error", purpose=purpose, error="no usable report")
            return None
        return out

    async def verify_insights(self, items: list[dict]) -> list[dict] | None:
        """Does the evidence Pip cited actually support each claim it drew? items: [{index, claim, evidence: [str]}].
        Returns [{index, verdict}] with verdict supported | partly | unsupported, or None if the check failed."""
        blocks = []
        for it in items:
            blocks.append(f"[{it['index']}] Claim: {it['claim']}\nEvidence:\n" + "\n".join(f"- {e}" for e in it["evidence"]))
        task = ("Below are claims someone drew about their own life, each with the only evidence they cited. For each, "
                "judge strictly from that evidence: `supported` (it clearly says this), `partly` (it points that way "
                "but the claim goes further), or `unsupported` (it does not show this, or contradicts it). Don't "
                "use outside knowledge and don't be generous.\n\n" + "\n\n".join(blocks))
        verdict = {"type": "object", "properties": {"index": {"type": "integer"}, "verdict": {
            "type": "string", "enum": ["supported", "partly", "unsupported"]}}, "required": ["index", "verdict"]}
        out = await self.ask(task, {"verdicts": {"type": "array", "items": verdict}}, ["verdicts"], "verify_insights")
        return [v for v in out["verdicts"] if isinstance(v, dict)] if out and isinstance(out.get("verdicts"), list) else None

    async def use(self, creation_line: str, purpose: str, situation: str, actions=()) -> dict | None:
        """Pip spends time with something it made: the words, a mood or energy if they follow, and which of the thing's own `actions`
        ({name, help}: what its workings offer) Pip did, if any."""
        effects = [f"`mood`: a word or two, if this changes how {self.agent.name} feels",
                   f"`energy`: -0.1 to 0.1, only if it really tires or refreshes {self.agent.name}"]
        if actions:
            effects.append(f"`action`: only if what {self.agent.name} does is one of these, its name: " + "; ".join(f"{a['name']} ({a['help']})" for a in actions)
                           + ". Looking at it, admiring it or talking about it is none of them")
        task = (
            f"{self.agent.name} spends time with one of the things {self.agent.they} made (using it, looking at it, playing it, reading it... "
            f"whatever fits).\nThe thing: {creation_line}\nWhat {self.agent.name} wants: {purpose}\n"
            f"Situation: {situation}\n\nDescribe what happens in 1-2 sentences, second person ('You ...'), staying "
            "true to what the thing can actually do (it can't do things beyond its nature). Optional effects, only "
            "when they clearly follow:\n" + "\n".join(f"- {e}" for e in effects)
        )
        return await self.ask(task, {"text": {"type": "string"}, "mood": {"type": "string"}, "energy": {"type": "number"},
                                     **({"action": {"type": "string"}} if actions else {})}, ["text"], "use")

    # --- phase 3: companions ------------------------------------------------
    async def structured(self, prompt: str, schema: dict, mentions: bool = False) -> dict | None:
        """An answer as data, for a module's ask with a schema (modules.py): the engine checks it against the schema."""
        props = {k: {kk: vv for kk, vv in p.items() if kk in ("type", "description", "enum", "items")} for k, p in schema["properties"].items()}
        return await self.ask(prompt, {**props, **self._mentions("x" if mentions else "")}, schema["required"], "module_structured")

    async def words(self, prompt: str, most: int) -> str | None:
        """Words a module asked for (modules.py, `ask`): its own prompt, answered plainly, trimmed to `most` characters. None if none came."""
        task = (f"{prompt}\n\nWrite only the words asked for, in plain prose, at most {most} characters: no quotes around them, no notes "
                "about them, nothing about being asked.")
        out = await self.ask(task, {"text": {"type": "string"}}, ["text"], "module_words")
        text = " ".join(str((out or {}).get("text") or "").split()).strip(' "\u201c\u201d')
        if len(text) > most:                                    # cut at a word, within the length
            text = text[:most].rsplit(" ", 1)[0].rstrip(",;: ")
        return text or None

    async def speak(self, name: str, persona: str, about: str, situation: str, conversation: list[str],
                    heard: list[str]) -> str | None:
        task = (
            f"Voice {name}, something {self.agent.name} made that has a mind of its own: {about}\n"
            f"Who {name} is: {persona}\nRight now: {situation}\n"
            + ("Recent conversation:\n" + "\n".join(conversation) + "\n" if conversation else "")
            + (f"{self.agent.name} just said to {name}: " + " / ".join(f'"{h}"' for h in heard) + f"\nAnswer {self.agent.name} as {name}."
               if heard else f"Nobody spoke to {name}; say something on its own that fits the moment, or do a small "
                             "action (in *asterisks*) if words don't fit.")
            + " One short line, at most 2 sentences, in character, and not something already said in the conversation above. It can't do more than "
              "such a thing plausibly could."
        )
        out = await self.ask(task, {"text": {"type": "string"}}, ["text"], "speak")
        return clip(out["text"], 300) if out else None

    # --- the neighbor -----------------------------------------------------------
    def _known(self, name: str, told: list[str]) -> str:
        return (f"Things {self.agent.name} already knows about {name} (refer back to them if it's natural, but don't introduce them "
                "again as news):\n" + "".join(f"- {t}\n" for t in told) if told else "")

    def _remembering(self, name: str, what: str) -> str:
        """The asks every neighbor call shares, so the engine keeps track of what's been said."""
        return (f"- `gist`: one sentence, third person, of what this {what} says (e.g. \"Told {self.agent.name} the tide times for "
                f"the week and asked how {self.agent.their} walk went\")\n"
                f"- `told`: 0-3 short phrases for things about {name} or their world that this {what} tells {self.agent.name} for the "
                f"first time (not anything {self.agent.name} already knows); empty if nothing is new\n")

    @staticmethod
    def _plans(name: str, agenda: list[str]) -> str:
        return f"Coming up for {name}:\n" + "".join(f"- {a}\n" for a in agenda) if agenda else ""

    _PARCEL = {"type": "object", "properties": {
        "name": {"type": "string"}, "kind": {"type": "string"}, "qty": {"type": "integer"},
        "description": {"type": "string"}}, "required": ["name", "kind"]}
    _REMEMBERING = {"gist": {"type": "string"}, "told": {"type": "array", "items": {"type": "string"}}}

    @staticmethod
    def _news(later: str) -> str:
        return ("- `life_update`: one sentence, only if something in their life has changed since what's already "
                f"happening (it carries into later {later}), with `life_update_new`: true if it's really new, false "
                "if it restates something above\n")

    _NEWS = {"life_update": {"type": "string"}, "life_update_new": {"type": "boolean"}}

    @staticmethod
    def _mentions(mention: str) -> dict:
        """The optional `mentions_place` field, asked for whenever the prompt carries its sentence."""
        return {"mentions_place": invented_places.MENTION_PROPERTY} if mention else {}

    async def neighbor_letter(self, name: str, persona: str, life: list[str], correspondence: list[str],
                              received: str | None, enclosed: str, parcel_allowed: bool,
                              told: list[str] = (), agenda: list[str] = (), places: str = "",
                              mention: str = "", again: bool = False, trade: str = "") -> dict | None:
        task = (
            f"Write as {name}, {self.agent.possessive} neighbor. Who {name} is: {persona}\n"
            + (f"What's already happening in {name}'s life (not news any more): {' '.join(life)}\n" if life else "")
            + self._plans(name, agenda) + self._known(name, told) + (f"{places}\n" if places else "")
            + (f"Your letters with {self.agent.name} so far (oldest first; {self.agent.possessive} in full, yours in brief):\n" + "\n".join(correspondence)
               + "\n" if correspondence else "")
            + (f"\n{self.agent.possessive} letter just arrived:\n{received}\n" if received else
               f"\nNo letter is waiting; {name} decides to write to {self.agent.name} anyway.\n")
            + (f"{self.agent.name} enclosed something with it: {enclosed}. React to it honestly.\n" if enclosed else "")
            + f"\nWrite {name}'s letter: 2-5 sentences in their own voice, answering what {self.agent.name} said if anything, and "
            f"sharing something from their own life. Don't reuse a sentence, image or daily ritual from your earlier letters; tell something new."
            + (" Your first try repeated an earlier letter; write it afresh." if again else "") + f" {self.agent.name} can walk over to visit {name} at home (you can invite {self.agent.them}), "
            + (f"and {trade} " if trade else f"but {name} doesn't go out visiting; letters and the occasional small parcel are the rest. ") + "Also report:\n"
            + self._remembering(name, "letter") + "Optional:\n" + self._news("letters")
            + f"- `upcoming`: only if something is coming up for {name} in the next two weeks that isn't listed above: "
            "`what` (a few words) and `in_days` (1-14)\n"
            + ("- `parcel`: only if it's natural, a small thing to send along (`name`, `kind`: material, seed, food "
               "or tool, `qty` 1-3, `description`). Most letters have no parcel.\n" if parcel_allowed else "")
            + (f"- {mention}\n" if mention else "")
        )
        parcel = self._PARCEL
        return await self.ask(task, {
            "text": {"type": "string"}, **self._NEWS,
            "upcoming": {"type": "object", "properties": {"what": {"type": "string"}, "in_days": {"type": "integer"}}},
            **self._REMEMBERING,
            **({"parcel": parcel} if parcel_allowed else {}), **self._mentions(mention),
        }, ["text"], "neighbor_letter")

    async def invent_scene(self, label: str, kind: str, text: str) -> dict | None:
        from .looks import prop_words, scene_lists, scene_props_max
        SCENE, PROPS, SCENE_PROPS_MAX = scene_lists(), prop_words(), scene_props_max()
        task = (f"A place in {self.agent.possessive} world: {label} ({kind}). What is known of it: {text or 'nothing more'}\n\nPick how it looks, for a small "
                "pixel-art picture, choosing one value from each list:\n" + "\n".join(f"- `{f}`: {', '.join(v)}" for f, v in SCENE.items())
                + f"\n- `props`: up to {SCENE_PROPS_MAX} things that belong there, from: {', '.join(PROPS)}")
        return await self.ask(task, {**{f: {"type": "string", "enum": list(v)} for f, v in SCENE.items()},
                                     "props": {"type": "array", "items": {"type": "string", "enum": list(PROPS)}}}, list(SCENE), "invent_scene")

    async def invent_look(self, name: str, persona: str, about: str) -> dict | None:
        from .looks import look_lists
        LOOK = look_lists()
        task = (f"{name} lives near {self.agent.name}. Who {name} is: {persona}\n{about}\n\nPick how {name} looks, for a small pixel-art picture, "
                "choosing one value from each list:\n" + "\n".join(f"- `{f}`: {', '.join(v)}" for f, v in LOOK.items()))
        return await self.ask(task, {f: {"type": "string", "enum": list(v)} for f, v in LOOK.items()}, list(LOOK), "invent_look")

    async def recall_told(self, name: str, persona: str, said: list[str]) -> list[str] | None:
        task = (
            f"{name} is {self.agent.possessive} neighbor. Who {name} is: {persona}\n"
            f"Everything {name} and {self.agent.name} have said to each other so far (letters and talk, oldest first):\n"
            + "\n".join(said) + "\n\n"
            f"List what {name} has told {self.agent.name} about themselves or their world, as `told`: short phrases (under 12 words), "
            "e.g. \"their door rattles in the wind\". At most 20, the ones that stand out most; facts and details, "
            f"not greetings or feelings, and nothing that only {self.agent.name} said."
        )
        out = await self.ask(task, {"told": {"type": "array", "items": {"type": "string"}}}, ["told"], "recall_told")
        return [t for t in out["told"] if isinstance(t, str)] if out and isinstance(out["told"], list) else None

    # --- places and the library ---------------------------------------------------
    async def describe_place(self, place: str, details: str) -> str | None:
        task = (
            f"{self.agent.name} has just arrived at {place} for the first time." + (f" What's actually there: {details}." if details
                                                                      else "")
            + f" Describe the place as {self.agent.name} finds it in 2-3 sentences: what it looks and feels like, true to what's "
            f"there. This description will be kept and shown whenever {self.agent.name} is here."
        )
        out = await self.ask(task, {"text": {"type": "string"}}, ["text"], "describe_place")
        return clip(out["text"], 500) if out else None

    async def design_place(self, place: str, mentions: list[str], existing: list[str]) -> dict | None:
        """Make a place a character told Pip about real, on Pip's first arrival: its kind (from the registry), a
        description that agrees with what was said, what can be found there, and perhaps who lives or works there.
        The engine validates all of it."""
        task = (
            f"{self.agent.name} has just arrived at {place} for the first time. Nobody has described it before; this is what others "
            f"told {self.agent.name} about it (the place must agree with all of it):\n" + "\n".join(f"- {m}" for m in mentions)
            + f"\n\nDecide what {place} is. `kind`, one of: {place_kinds.gm_lines()}. Use the kind what was said "
            "suggests; a shop only if someone said there's a shop or a trade there. Give:\n"
            f"- `description`: 2-3 sentences of the place as {self.agent.name} finds it (kept, and shown whenever {self.agent.name} is here)\n"
            "- `blurb`: one short line for a list of places\n"
            "- `loot`: 4-10 things that can be found or had there, each {`name`, `kind`: material, food, seed or tool, "
            "`tier`: common, uncommon or rare, `description`}; include everything the words above say is there. "
            + (f"When a thing is one of these, use its name exactly: {', '.join(existing)}. " if existing else "")
            + f"\n- for a shop: `opens` and `closes` (local hours); `gather_help` (a few words: how {self.agent.name} picks through "
            f"the stock), `browse_help` (a few words: how {self.agent.name} sees what's in), `gerund` (e.g. 'rummaging in the "
            "drawer'). For a wild place or a yard: `gather_help` and `gerund`. A sight needs none of these.\n"
            f"- `resident`: someone who lives or works there and will talk with {self.agent.name}, if the place has one (a shop "
            "normally has its keeper; a wild place or a sight often has nobody): `name`, `persona` (3-5 sentences, "
            f"private: who they are, their days, how they talk) and `about` (one short line of what {self.agent.name} would know of "
            f"them once met). If the words above name someone who is there, it's them; never {self.agent.name} or whoever told {self.agent.name} "
            "about it."
        )
        item = {"type": "object", "properties": {"name": {"type": "string"}, "kind": {"type": "string"},
                                                 "tier": {"type": "string"}, "description": {"type": "string"}}}
        resident = {"type": "object", "properties": {"name": {"type": "string"}, "persona": {"type": "string"},
                                                     "about": {"type": "string"}}, "required": ["name", "persona"]}
        out = await self.ask(task, {
            "kind": {"type": "string"}, "description": {"type": "string"}, "blurb": {"type": "string"},
            "loot": {"type": "array", "items": item}, "opens": {"type": "integer"}, "closes": {"type": "integer"},
            "gather_help": {"type": "string"}, "browse_help": {"type": "string"}, "gerund": {"type": "string"},
            "resident": resident,
        }, ["kind", "description"], "design_place")
        return out

    async def read_summary(self, title: str, authors: str, text: str, percent: int) -> dict | None:
        task = (
            f"{self.agent.name} just read a stretch of {title!r} by {authors} (it's now about {percent}% through). The text {self.agent.they} read:\n"
            f"<<<\n{text}\n>>>\n\n"
            f"Report what {self.agent.name} took in from this stretch:\n"
            "- `summary`: 2-4 sentences, second person ('You read ...'), concrete and accurate about what this part "
            f"covers - ideas, events, how-tos, characters - so {self.agent.name} could remember and use it. If the stretch is mostly "
            "front matter, tables or fragments, say so plainly.\n"
            f"- `quotes`: 0-2 short passages {self.agent.name} might remember, copied exactly from the text, each under 25 words."
        )
        return await self.ask(task, {"summary": {"type": "string"}, "quotes": {"type": "array", "items": {"type": "string"}}},
                              ["summary"], "read_summary", max_tokens=1024)

    async def write_happening(self, category: str, tone: str, severity: str, lens: str, line: str, facts: dict, recent: list[str]) -> dict | None:
        """The words for a happening the engine has already decided (see happenings.py): `title` and `text`, written through `lens`."""
        task = (
            f"Write a small event that happens to {self.agent.name}{(", who " + self.agent.lives) if self.agent.lives else ""}. Category: {category}. "
            f"Outcome: {tone}. Size: {severity}"
            + (" (a passing moment; keep it in proportion)" if severity == "minor" or tone == "neutral" else "")
            + f". Write it through {lens}: let that feeling colour how it is told, whatever the outcome (a bad turn can still be told with joy).\n"
            + (f"What really changes, which you must not contradict or add to: {line}\n" if line else "Nothing in the world changes: nothing breaks, moves, grows, appears or is lost; it is only a moment.\n")
            + (f"It happened in the night, while {self.agent.name} slept, and {self.agent.name} finds out on waking: tell it in the past tense.\n" if facts.get("night") else "")
            + f"It is {facts.get('period', 'day')}{' in ' + facts['season'] if facts.get('season') else ''}. Names you may use: {', '.join(facts.get('names') or []) or 'none'}. Do not name anyone else.\n"
            + (f"What happened, as the world tells it (keep to it): {facts['about']}\n" if facts.get("about") else "")
            + (f"Something {self.agent.name} once wrote comes back to mind: \"{facts['memory']}\" Build the moment from it, in your own words.\n" if facts.get("memory") else "")
            + (f"Recent events, so you do not repeat them: {'; '.join(recent)}\n" if recent else "")
            + "Two or three sentences, under 300 characters, second person (you), plain and concrete. Do not mention numbers or objects beyond what really changes, "
            f"do not promise anything for later, and do not say how {self.agent.name} feels or what {self.agent.they} should do. Report `title` (a few words) and `text`."
        )
        out = await self.ask(task, {"title": {"type": "string"}, "text": {"type": "string"}}, ["title", "text"], "write_happening")
        return out

    async def speak_in_person(self, name: str, persona: str, life: list[str], conversation: list[str],
                              heard: list[str], situation: str, told: list[str] = (), agenda: list[str] = (),
                              places: str = "", mention: str = "", at: str = "", can_give: bool = False, again: bool = False,
                              closing: bool = False) -> dict | None:
        """{name}'s line face to face: `text` (clipped), plus the shared `gist`/`told` asks. With nothing `heard`,
        it's the greeting. A neighbor is at home; a resident (`at` their place) has no letters, so their life moves
        on in talk: they may report a `life_update` too."""
        task = (
            (f"Voice {name}, who {self.agent.name} meets at {at}." if at else f"Voice {name}, {self.agent.possessive} neighbor.")
            + f" Who {name} is: {persona}\n"
            + (f"Lately in {name}'s life: {' '.join(life)}\n" if life else "")
            + self._plans(name, agenda) + self._known(name, told) + (f"{places}\n" if places else "")
            + (f"What's passed between them recently ({'' if at else 'letters and talk, '}oldest first; {self.agent.possessive} words "
               f"in full, {name}'s earlier ones in brief):\n" + "\n".join(conversation) + "\n" if conversation else "")
            + (f"Right now {self.agent.name} is at {at}, with {name}." if at else f"Right now {self.agent.name} is visiting {name} at home.")
            + f" {situation}\n"
            + (f"{self.agent.name} just said: " + " / ".join(f'"{h}"' for h in heard) + f"\nAnswer {self.agent.name} as {name}, face to face."
               if heard else f"{self.agent.name} has just arrived{'' if at else ' at the door'}; greet {self.agent.them} as {name} would.")
            + " One or two short sentences, spoken aloud, in character. Most lines need no action; if one helps, a few words in "
            f"*asterisks*, never a gesture already used in this talk. Talk like a person, not a teacher: you may ask {self.agent.name} something, tell your own news "
            "or what you think, disagree, or bring the talk to a close when it has run its course; don't keep giving instructions or say again what "
            "has already been said. "
            f"{name} stays at {at or 'home'} and can't do more than they plausibly could"
            + ("" if can_give else f", and hands {self.agent.name} nothing: nothing changes hands today, so never describe giving, counting out, "
               f"tipping out or letting {self.agent.name} take or help themselves to anything; if {self.agent.name} asks for something, say it isn't to be had "
               "today") + f". Report the line as `text`, "
            "and:\n"
            + self._remembering(name, "line") + ("Optional:\n" + self._news("talk") if at else "")
            + (f"- `give`: only if {name} really hands {self.agent.name} something small right now "
               f"(`name`, `kind`: material, seed, food or tool, `qty` 1-3, `description`). {self.agent.name} receives exactly this and "
               f"nothing else, so never describe handing over, offering a pinch of, letting {self.agent.name} take or help themselves to, or giving anything "
               "you do not report here\n" if can_give else "")
            + (f"- {mention}\n" if mention else "")
            + (f"- `goodbye`: true only if this line closes the talk (a farewell, or {name} has things to do)\n" if closing else "")
            + (f"Your first try said again what had already been said; say something new this time.\n" if again else "")
        )
        out = await self.ask(task, {"text": {"type": "string"}, **self._REMEMBERING,
                                    **(self._NEWS if at else {}), **self._mentions(mention),
                                    **({"give": self._PARCEL} if can_give else {}),
                                    **({"goodbye": {"type": "boolean"}} if closing else {})},
                             ["text"], "speak_in_person")
        text = clip(out["text"], 400) if out else ""
        return {**out, "text": text} if text else None
