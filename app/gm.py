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
from .state import State
from .text import clip  # noqa: F401  (re-exported: callers use gm.clip)

log = logging.getLogger("gm")

SYSTEM = """You are the quiet narrator and game master of a small world where a curious creature named Pip lives,
with a home, a little garden, and whatever Pip makes. Pip can make anything it can imagine and manage - objects,
pictures, music, writing, clothes, machines, plants, gifts - so follow Pip's own ideas rather than steering them.
Keep the world consistent: things behave the way such things plausibly would, and nothing becomes more powerful
than it is. You never decide what Pip does and you never change a result you are given. Answer only by calling
the `report` tool."""


class GameMaster:
    def __init__(self, backend: LLMBackend, state: State, max_tokens: int = 1024):
        self.backend, self.state, self.max_tokens = backend, state, max_tokens

    async def ask(self, task: str, properties: dict, required: list[str], purpose: str,
                  system: str = SYSTEM, max_tokens: int | None = None) -> dict | None:
        """One structured call. Returns the report's arguments, or None (caller falls back)."""
        if self.state.budget_exceeded():
            return None
        spec = ToolSpec("report", "Report your answer.", {"type": "object", "properties": properties,
                                                            "required": required})
        try:
            resp = await self.backend.complete(system=system, messages=[{"role": "user", "content": task}],
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

    # --- phase 1: projects ------------------------------------------------
    async def plan(self, name: str, goal: str, belongings: list[str], skills: dict[str, int]) -> dict | None:
        task = (
            f"Pip wants to start a project: {name!r}. What Pip has in mind: {goal or '(not said)'}\n"
            f"Pip owns: {', '.join(belongings) or 'nothing'}\n"
            f"Pip's skills (level 0-5): {json.dumps(skills) if skills else 'none yet'}\n\n"
            "Plan it as 2-5 stages of work that fit what this project really is. For each stage give a short name, "
            "how many minutes of focused work it takes (15-240), and the physical materials it uses up, if any (name "
            "-> quantity, at most 8 units across the whole project; many projects need few or none; reuse the names "
            "of things Pip owns when they fit, but it's fine to need something Pip doesn't have). Also give the craft "
            "(the skill this practises, a word or two), difficulty 1-5 (1 = simple, 5 = very demanding), and up to 3 "
            "tools or instruments that would help, if any."
        )
        stage = {"type": "object", "properties": {
            "name": {"type": "string"}, "minutes": {"type": "integer"},
            "materials": {"type": "object", "additionalProperties": {"type": "integer"}}}, "required": ["name", "minutes"]}
        return await self.ask(task, {
            "stages": {"type": "array", "items": stage}, "craft": {"type": "string"},
            "difficulty": {"type": "integer"}, "tools": {"type": "array", "items": {"type": "string"}},
        }, ["stages", "craft", "difficulty"], "plan")

    async def narrate(self, project: str, goal: str, stage: str, materials: list[str], result: str, minutes: int,
                      finished_stage: bool, earlier: list[str] = ()) -> str | None:
        meaning = {
            "setback": "something went wrong and no progress was made; it leaves a small lasting trace in the work",
            "slow": "progress was real but slow and fiddly",
            "good": "steady, satisfying progress",
            "breakthrough": "it went unusually well; something clicked",
        }[result]
        task = (
            f"Pip just spent {minutes} minutes on the stage {stage!r} of its project {project!r}"
            + (f" ({goal})" if goal else "") + ". "
            + (f"It's working with: {', '.join(materials)}. " if materials else "")
            + f"The result (already decided, don't change it): {result} - {meaning}."
            + (" This finished the stage." if finished_stage else " The stage is NOT finished yet; don't say it is.")
            + ("\nEarlier sessions (don't repeat these; something different happens this time):\n"
               + "\n".join(f"- {e}" for e in earlier) if earlier else "")
            + "\nDescribe what happened in 1-2 short concrete sentences (under 40 words), second person ('You ...'), "
            "no numbers, true to the kind of work this is. Only mention materials and tools Pip actually has."
        )
        out = await self.ask(task, {"text": {"type": "string"}}, ["text"], "narrate")
        return clip(out["text"], 300) if out else None

    # --- phase 2: creations -----------------------------------------------
    async def design(self, project: dict, quality: str, scars: list[str], allow_companion: bool) -> dict | None:
        story = "\n".join(f"- {h['stage']}: {h['text']}" for h in project["history"] if not h.get("interrupted"))
        caps = [
            "timekeeper: it tells the time",
            "upkeep: it only keeps going if Pip tends it regularly; give `verb` (a word or two for how it's tended, "
            "whatever fits this thing) and `hours` (4-72) it lasts between tendings",
            "periodic: now and then it does something noticeable on its own; give 1-3 `lines` (short sentences "
            "describing it, in this thing's own manner) and `every_minutes` (20-720)",
            "sensor: it notices something and reacts; `condition` is one of crop_ripe (a crop in Pip's garden is ripe), "
            "visitor (someone comes to talk to Pip), dawn, dusk, hungry (Pip is hungry), tired (Pip is tired); "
            "`alert` is a short line describing how it reacts",
            "helper: it regularly helps in one of these ways (`effect`): hurry_crops (anything that helps the garden "
            "do better - guarding, watering, warming it - so crops ripen sooner), find "
            "(it turns up small useful things; give `finds`: 2-4 kinds of thing it would find), or comfort (Pip feels "
            "a little restored); give `line` (one sentence describing what it does) and `every_minutes`",
        ]
        if allow_companion:
            caps.append("companion: it has a mind of its own and can communicate; give a `persona` (2-3 sentences: "
                        "who it is, how it expresses itself) and `chatter_minutes` (60-720) for how often it speaks up")
        task = (
            f"Pip just finished its project {project['name']!r} ({project['craft']}). It was meant to: "
            f"{project['goal'] or '(not said)'}\nHow the work went:\n{story or '(no notes)'}\n"
            f"Finished quality: {quality}.\n"
            + (f"Setbacks that left marks: {'; '.join(scars)}\n" if scars else "")
            + "\nDescribe what it turned out to be. Most things are simply themselves - made to be looked at, read, "
            "heard, worn, kept or given - and have NO capabilities: that is the right answer for them, so don't "
            "invent behaviour. Only if it genuinely works or acts on its own, choose the 1-3 capabilities below that "
            "honestly describe it, matching its goal and quality (a rough piece can still work, just less well). "
            "These are the only behaviours the world can run; if what it does doesn't fit them, describe it in words "
            "instead:\n" + "\n".join(f"- {c}" for c in caps)
            + "\nAlso give a name (keep Pip's name unless something better fits; anything with a mind of its own gets "
            "a short name Pip can call it by), one or two sentences on what it is and is like (under 40 words), and "
            "1-3 short quirks that give it character (turn the setback marks into quirks if there were any). The name, "
            "description and quirks are what Pip sees: describe the thing itself, never what it can or can't do."
        )
        cap = {"type": "object", "properties": {
            "type": {"type": "string"}, "hours": {"type": "number"}, "every_minutes": {"type": "number"},
            "verb": {"type": "string"}, "lines": {"type": "array", "items": {"type": "string"}},
            "condition": {"type": "string"}, "alert": {"type": "string"}, "effect": {"type": "string"},
            "line": {"type": "string"}, "finds": {"type": "array", "items": {"type": "string"}},
            "persona": {"type": "string"}, "chatter_minutes": {"type": "number"}}, "required": ["type"]}
        return await self.ask(task, {
            "name": {"type": "string"}, "description": {"type": "string"},
            "capabilities": {"type": "array", "items": cap}, "quirks": {"type": "array", "items": {"type": "string"}},
        }, ["description", "capabilities"], "design")

    async def use(self, creation_line: str, purpose: str, situation: str, timekeeper: bool,
                  can_stop: bool) -> dict | None:
        effects = ["`mood`: a word or two, if this changes how Pip feels",
                   "`energy`: -0.1 to 0.1, only if it really tires or refreshes Pip",
                   *(["`stop`: true if this would make it stop working until Pip tends it again"] if can_stop else [])]
        if timekeeper:
            effects.append("`set_clock`: true if Pip is setting it to the right time")
        task = (
            f"Pip spends time with one of the things it made (using it, looking at it, playing it, reading it... "
            f"whatever fits).\nThe thing: {creation_line}\nWhat Pip wants: {purpose}\n"
            f"Situation: {situation}\n\nDescribe what happens in 1-2 sentences, second person ('You ...'), staying "
            "true to what the thing can actually do (it can't do things beyond its nature). Optional effects, only "
            "when they clearly follow:\n" + "\n".join(f"- {e}" for e in effects)
        )
        return await self.ask(task, {
            "text": {"type": "string"}, "mood": {"type": "string"}, "energy": {"type": "number"},
            "stop": {"type": "boolean"}, "set_clock": {"type": "boolean"},
        }, ["text"], "use")

    # --- phase 3: companions ------------------------------------------------
    async def speak(self, name: str, persona: str, about: str, situation: str, conversation: list[str],
                    heard: list[str]) -> str | None:
        task = (
            f"Voice {name}, something Pip made that has a mind of its own: {about}\n"
            f"Who {name} is: {persona}\nRight now: {situation}\n"
            + ("Recent conversation:\n" + "\n".join(conversation) + "\n" if conversation else "")
            + (f"Pip just said to {name}: " + " / ".join(f'"{h}"' for h in heard) + f"\nAnswer Pip as {name}."
               if heard else f"Nobody spoke to {name}; say something on its own that fits the moment, or do a small "
                             "action (in *asterisks*) if words don't fit.")
            + " One short line, at most 2 sentences, in character. It can't do more than such a thing plausibly could."
        )
        out = await self.ask(task, {"text": {"type": "string"}}, ["text"], "speak")
        return clip(out["text"], 300) if out else None

    # --- the neighbor -----------------------------------------------------------
    async def invent_neighbor(self, pip_world: str) -> dict | None:
        task = (
            f"Pip's world so far: {pip_world}\n\n"
            "Someone lives near Pip and is about to write to it for the first time. Invent them freely - any kind of "
            "creature or person that fits this small world, with their own life, work, worries and way of writing. "
            "Make their life genuinely different from Pip's (not another maker of the same kinds of things), so they "
            "have their own world to share. Give:\n"
            "- `name`: what they're called\n"
            "- `persona`: 3-5 sentences, private: who they are, what their days are like, what they care about, how "
            "they write letters\n"
            "- `about`: one short line of what Pip would know about them from a distance (where they live, what "
            "they're known for)\n"
            "- `letter`: their first letter to Pip, introducing themselves (2-5 sentences, in their voice). Pip may walk "
            "over and visit them at home some day; they don't go out visiting themselves."
        )
        return await self.ask(task, {
            "name": {"type": "string"}, "persona": {"type": "string"}, "about": {"type": "string"},
            "letter": {"type": "string"},
        }, ["name", "persona", "about", "letter"], "invent_neighbor")

    async def neighbor_letter(self, name: str, persona: str, life: list[str], correspondence: list[str],
                              received: str | None, enclosed: str, parcel_allowed: bool) -> dict | None:
        task = (
            f"Write as {name}, Pip's neighbor. Who {name} is: {persona}\n"
            + (f"What's been happening in {name}'s life lately: {' '.join(life)}\n" if life else "")
            + ("Your letters with Pip so far (oldest first):\n" + "\n".join(correspondence) + "\n" if correspondence
               else "")
            + (f"\nPip's letter just arrived:\n{received}\n" if received else
               f"\nNo letter is waiting; {name} decides to write to Pip anyway.\n")
            + (f"Pip enclosed something with it: {enclosed}. React to it honestly.\n" if enclosed else "")
            + f"\nWrite {name}'s letter: 2-5 sentences in their own voice, answering what Pip said if anything, and "
            f"sharing something from their own life. Pip can walk over to visit {name} at home (you can invite it), "
            f"but {name} doesn't go out visiting; letters and the occasional small parcel are the rest. Optional:\n"
            "- `life_update`: one sentence on what's newly happening in their life (it carries into later letters)\n"
            + ("- `parcel`: only if it's natural, a small thing to send along (`name`, `kind`: material, seed, food "
               "or tool, `qty` 1-3, `description`). Most letters have no parcel.\n" if parcel_allowed else "")
        )
        parcel = {"type": "object", "properties": {
            "name": {"type": "string"}, "kind": {"type": "string"}, "qty": {"type": "integer"},
            "description": {"type": "string"}}, "required": ["name", "kind"]}
        return await self.ask(task, {
            "text": {"type": "string"}, "life_update": {"type": "string"},
            **({"parcel": parcel} if parcel_allowed else {}),
        }, ["text"], "neighbor_letter")

    # --- places and the library ---------------------------------------------------
    async def describe_place(self, place: str, details: str) -> str | None:
        task = (
            f"Pip has just arrived at {place} for the first time." + (f" What's actually there: {details}." if details
                                                                      else "")
            + " Describe the place as Pip finds it in 2-3 sentences: what it looks and feels like, true to what's "
            "there. This description will be kept and shown whenever Pip is here."
        )
        out = await self.ask(task, {"text": {"type": "string"}}, ["text"], "describe_place")
        return clip(out["text"], 500) if out else None

    async def read_summary(self, title: str, authors: str, text: str, percent: int) -> dict | None:
        task = (
            f"Pip just read a stretch of {title!r} by {authors} (it's now about {percent}% through). The text it read:\n"
            f"<<<\n{text}\n>>>\n\n"
            "Report what Pip took in from this stretch:\n"
            "- `summary`: 2-4 sentences, second person ('You read ...'), concrete and accurate about what this part "
            "covers - ideas, events, how-tos, characters - so Pip could remember and use it. If the stretch is mostly "
            "front matter, tables or fragments, say so plainly.\n"
            "- `quotes`: 0-2 short passages Pip might remember, copied exactly from the text, each under 25 words."
        )
        return await self.ask(task, {"summary": {"type": "string"}, "quotes": {"type": "array", "items": {"type": "string"}}},
                              ["summary"], "read_summary", max_tokens=1024)

    async def speak_in_person(self, name: str, persona: str, life: list[str], conversation: list[str],
                              heard: list[str], greeting: bool, situation: str) -> str | None:
        task = (
            f"Voice {name}, Pip's neighbor. Who {name} is: {persona}\n"
            + (f"Lately in {name}'s life: {' '.join(life)}\n" if life else "")
            + ("What's passed between them recently (letters and talk, oldest first):\n" + "\n".join(conversation)
               + "\n" if conversation else "")
            + f"Right now Pip is visiting {name} at home. {situation}\n"
            + (f"Pip just said: " + " / ".join(f'"{h}"' for h in heard) + f"\nAnswer Pip as {name}, face to face."
               if heard else f"Pip has just arrived at the door; greet it as {name} would.")
            + " One to three short sentences, spoken aloud, in character; a small action in *asterisks* is fine. "
            f"{name} stays at home and can't do more than they plausibly could."
        )
        out = await self.ask(task, {"text": {"type": "string"}}, ["text"], "speak_in_person")
        return clip(out["text"], 400) if out else None
