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
from . import abilities
from . import world_effects
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
    async def review_start(self, name: str, goal: str, steps: list[dict], belongings: list[str],
                           feelings: list[str]) -> dict | None:
        """Review Pip's own plan. The GM doesn't write the steps; it tags them, judges the project, and holds the
        truth about what Pip can't know yet."""
        listing = "\n".join(f"{i}. {s['name']} (Pip thinks ~{s['minutes']} min"
                            + (", using " + ", ".join(f"{q} {n}" for n, q in s["materials"].items()) if s["materials"] else "")
                            + ")" for i, s in enumerate(steps))
        task = (
            f"Pip wants to start a project: {name!r}. What Pip has in mind: {goal or '(not said)'}\n"
            f"Pip's own plan, in its own words:\n{listing}\n"
            f"Pip owns: {', '.join(belongings) or 'nothing'}\n"
            + ("About Pip: " + " ".join(feelings) + "\n" if feelings else "")
            + "\nThis is Pip's plan: do not rewrite, add or remove steps. Review it. For each step (same order, same "
            "count) give the 1-2 `abilities` it exercises, from: precision, patience, ingenuity, knowledge, handiness, "
            "and correct `minutes` only if Pip's guess is badly off (15-240). Give the project's `craft` (a word or "
            "two), `difficulty` 1-5, and up to 3 `tools` or instruments that would help. Then decide what Pip "
            "cannot know yet: if there are real unknowns in making this (anything about finding out, tuning or how "
            "the thing really behaves), list up to 3 `open_questions` (short) and 1-3 `hidden` facts: how the thing "
            "really works, consistent with each other and plausibly able to trip up Pip's plan. Pip never sees "
            "hidden facts until it discovers them. If the path is plain, leave both empty. Finally `concerns`: one "
            "short sentence only if something in the plan is obviously unworkable to anyone with Pip's experience "
            "(otherwise empty); don't hint at hidden facts."
        )
        step = {"type": "object", "properties": {"abilities": {"type": "array", "items": {"type": "string"}},
                                                  "minutes": {"type": "integer"}}}
        return await self.ask(task, {
            "steps": {"type": "array", "items": step}, "craft": {"type": "string"},
            "difficulty": {"type": "integer"}, "tools": {"type": "array", "items": {"type": "string"}},
            "open_questions": {"type": "array", "items": {"type": "string"}},
            "hidden": {"type": "array", "items": {"type": "string"}}, "concerns": {"type": "string"},
        }, ["craft", "difficulty"], "review")

    async def adjudicate(self, project: dict, stage: dict, approach: str, rolled: str, minutes: int,
                         materials: list[str], earlier: list[str], feelings: list[str]) -> dict | None:
        """Judge what Pip tried in a work session. The die has already said how things went in general; the GM
        weighs Pip's approach and may move the result one step either way (the engine enforces that)."""
        hidden = [h["fact"] for h in project["hidden"] if not h["found"]]
        meaning = {"blowup": "so badly it goes wrong in Pip's face", "setback": "poorly", "slow": "slowly but surely",
                   "good": "well", "breakthrough": "unusually well"}[rolled]
        task = (
            f"Project {project['name']!r} ({project['craft']}, difficulty {project['difficulty']}/5): "
            f"{project['goal'] or '(no stated goal)'}\n"
            f"Stage: {stage['name']!r}. Pip worked {minutes} minutes and described its approach: {approach!r}\n"
            + (f"It's working with: {', '.join(materials)}. " if materials else "")
            + ("About Pip: " + " ".join(feelings) + "\n" if feelings else "")
            + (f"Things Pip has found out so far: {'; '.join(project['findings'])}\n" if project["findings"] else "")
            + (f"Hidden truths about this project (Pip cannot see them): {'; '.join(hidden)}\n" if hidden else "")
            + f"The die says this kind of effort goes {meaning} on average. Decide the `verdict` for what Pip actually "
            "did: blowup, setback, slow, good or breakthrough. A sound, clever approach that respects how the "
            "thing really works may go one step better than the die says; a careless, wrong-headed or reckless one "
            "one step worse (the world won't allow more than one step either way). Blowup means it goes wrong in "
            "Pip's face (a snapped part, a burn, a spoiled piece): pick it only if the approach was reckless or "
            "clearly flawed. Never decide that Pip is finished with the stage. Write `text`: 1-3 concrete "
            "sentences, second person, under 50 words, true to this kind of work, using only what Pip has. If the "
            "attempt taught Pip something, give `finding` (one plain sentence); if it exposed one of the hidden "
            "truths, give its index in `reveal` (index = order listed, from 0)."
            + ("\nEarlier sessions (something different happens this time):\n" + "\n".join(f"- {e}" for e in earlier)
               if earlier else "")
        )
        return await self.ask(task, {
            "verdict": {"type": "string", "enum": ["blowup", "setback", "slow", "good", "breakthrough"]},
            "text": {"type": "string"}, "finding": {"type": "string"}, "reveal": {"type": "integer"},
        }, ["verdict", "text"], "adjudicate")

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

    # --- discovery ---------------------------------------------------------
    @staticmethod
    def _project_brief(project: dict) -> str:
        done = [s["name"] for s in project["stages"] if s["progress"] >= s["minutes"] - 1e-6]
        todo = [s["name"] for s in project["stages"] if s["progress"] < s["minutes"] - 1e-6]
        return (f"Project {project['name']!r} ({project['craft']}): {project['goal'] or '(no stated goal)'}\n"
                f"Done stages: {', '.join(done) or 'none'}. Remaining: {', '.join(todo) or 'none'}.\n"
                f"Open questions: " + ("; ".join(f"[{i}] {q}" for i, q in enumerate(project["questions"])) or "none")
                + "\nWhat Pip has found out so far: " + ("; ".join(project["findings"]) or "nothing yet"))

    _CHANGES = {
        "finding": {"type": "string"}, "reveal": {"type": "integer"}, "answers": {"type": "integer"},
    }

    async def experiment(self, project: dict, hypothesis: str, outcome: str, unfound: list[str],
                         found: list[str]) -> dict | None:
        meaning = {
            "nothing": "it showed nothing useful; say what Pip saw, without hinting at the answer",
            "clue": "it hinted at something, but nothing certain; the `finding` is only a partial, honest observation",
            "insight": "it worked: it shows one of the hidden facts, and Pip understands something real it did not",
            "surprise": "it showed one of the hidden facts and also something unexpected that opens a new direction",
        }[outcome]
        task = (
            self._project_brief(project) + f"\nHidden facts (index: fact; Pip cannot see these): "
            + ("; ".join(f"[{i}] {h['fact']}" + (" (already found)" if h["found"] else "")
                         for i, h in enumerate(project["hidden"])) or "none") + "\n"
            f"Pip ran an experiment. Its hypothesis: {hypothesis!r}.\n"
            f"The engine already rolled the outcome ({outcome}): {meaning}.\n"
            "Decide `relevant`: false if the hypothesis has nothing to do with the project or the hidden facts (then "
            "the result is simply inconclusive and `text` should say so). Write `text` (1-3 concrete sentences, "
            "second person, under 60 words) describing what Pip observed. For a clue, insight or surprise give "
            "`finding`: what Pip now knows, in one plain sentence, based on the hidden fact (do not reveal facts the "
            "outcome doesn't show). For an insight or surprise give `reveal` (the index of the hidden fact it shows) "
            "and, if it answers an open question, `answers` (that question's index). Pip decides what to do next; "
            "you don't add steps. For a surprise, `new_question` may name what Pip now "
            "wonders about, and `difficulty_delta` (-1, 0 or 1) says if it made the project easier or harder. "
            "Never decide that Pip succeeded or failed at the project itself."
        )
        props = {"relevant": {"type": "boolean"}, "text": {"type": "string"}, "new_question": {"type": "string"},
                 "difficulty_delta": {"type": "integer"}, **self._CHANGES}
        return await self.ask(task, props, ["relevant", "text"], "experiment")

    async def revise(self, project: dict, steps: list[dict], because: str) -> dict | None:
        """Annotate steps Pip just added to its plan, and judge whether knowledge Pip brings from elsewhere
        (a search, a book, a visitor) settles something it didn't know. Pip's steps are never changed."""
        parts = [self._project_brief(project)]
        if steps:
            parts.append("Pip added these steps to its own plan:\n" + "\n".join(
                f"{i}. {s['name']} (~{s['minutes']} min)" for i, s in enumerate(steps)))
        if because:
            parts.append("Hidden facts (index: fact; Pip cannot see these): "
                         + ("; ".join(f"[{i}] {h['fact']}" + (" (already found)" if h["found"] else "")
                                      for i, h in enumerate(project["hidden"])) or "none")
                         + f"\nPip says it learned, from elsewhere (reading, searching, a visitor): {because!r}.")
        task = "\n".join(parts) + "\n"
        if steps:
            task += ("For each added step (same order and count) give `steps` notes: 1-2 `abilities` from precision, "
                     "patience, ingenuity, knowledge, handiness, and `minutes` only if Pip's guess is badly off. "
                     "Do not rename, add or remove steps. ")
        if because:
            task += ("Decide `accepted`: true only if what Pip learned plausibly settles one of its open questions or "
                     "matches a hidden fact (otherwise false, and say kindly in `text` why it doesn't help). If "
                     "accepted, give `answers` (the open question's index) and/or `reveal` (a hidden fact's index, "
                     "only if the source would really contain it) with a `finding` (one plain sentence). ")
        task += "`text`: one or two sentences, second person. Never decide success or failure."
        step = {"type": "object", "properties": {"abilities": {"type": "array", "items": {"type": "string"}},
                                                  "minutes": {"type": "integer"}}}
        props = {"accepted": {"type": "boolean"}, "text": {"type": "string"},
                 "steps": {"type": "array", "items": step}, **self._CHANGES}
        return await self.ask(task, props, ["text"], "revise")

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
        caps.append(world_effects.gm_lines())
        caps.append(abilities.gm_lines())
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
            "persona": {"type": "string"}, "chatter_minutes": {"type": "number"}, "ability": {"type": "string"}}, "required": ["type"]}
        return await self.ask(task, {
            "name": {"type": "string"}, "description": {"type": "string"},
            "capabilities": {"type": "array", "items": cap}, "quirks": {"type": "array", "items": {"type": "string"}},
        }, ["description", "capabilities"], "design")

    async def use(self, creation_line: str, purpose: str, situation: str, timekeeper: bool,
                  can_stop: bool, bulletin: bool = False, tend_verb: str = "") -> dict | None:
        effects = ["`mood`: a word or two, if this changes how Pip feels",
                   "`energy`: -0.1 to 0.1, only if it really tires or refreshes Pip",
                   *(["`stop`: true if this would make it stop working until Pip tends it again"] if can_stop else [])]
        if tend_verb:
            effects.append(f"`tend`: true only if what Pip does is the regular upkeep that keeps it going (\"{tend_verb}\"): winding, "
                           "charging, oiling, feeding, whatever suits it. Looking at it, setting it or admiring it is not upkeep")
        if timekeeper:
            effects.append("`set_clock`: true if Pip is setting it to the right time")
        if bulletin:
            effects.append("`bulletin`: only if Pip is listening for news: 2-3 sentences of news about Pip's own small world only "
                           "(the weather, the neighbors, the season, something invented and harmless), never real-world events")
        task = (
            f"Pip spends time with one of the things it made (using it, looking at it, playing it, reading it... "
            f"whatever fits).\nThe thing: {creation_line}\nWhat Pip wants: {purpose}\n"
            f"Situation: {situation}\n\nDescribe what happens in 1-2 sentences, second person ('You ...'), staying "
            "true to what the thing can actually do (it can't do things beyond its nature). Optional effects, only "
            "when they clearly follow:\n" + "\n".join(f"- {e}" for e in effects)
        )
        return await self.ask(task, {
            "text": {"type": "string"}, "mood": {"type": "string"}, "energy": {"type": "number"},
            "stop": {"type": "boolean"}, "set_clock": {"type": "boolean"}, **({"bulletin": {"type": "string"}} if bulletin else {}),
            **({"tend": {"type": "boolean"}} if tend_verb else {}),
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
            + " One short line, at most 2 sentences, in character, and not something already said in the conversation above. It can't do more than "
              "such a thing plausibly could."
        )
        out = await self.ask(task, {"text": {"type": "string"}}, ["text"], "speak")
        return clip(out["text"], 300) if out else None

    # --- the neighbor -----------------------------------------------------------
    async def invent_neighbor(self, pip_world: str, mention: str = "") -> dict | None:
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
            + (f"\n{mention}" if mention else "")
        )
        return await self.ask(task, {
            "name": {"type": "string"}, "persona": {"type": "string"}, "about": {"type": "string"},
            "letter": {"type": "string"}, **self._mentions(mention),
        }, ["name", "persona", "about", "letter"], "invent_neighbor")

    @staticmethod
    def _known(name: str, told: list[str]) -> str:
        return (f"Things Pip already knows about {name} (refer back to them if it's natural, but don't introduce them "
                "again as news):\n" + "".join(f"- {t}\n" for t in told) if told else "")

    @staticmethod
    def _remembering(name: str, what: str) -> str:
        """The asks every neighbor call shares, so the engine keeps track of what's been said."""
        return (f"- `gist`: one sentence, third person, of what this {what} says (e.g. \"Told Pip the tide times for "
                f"the week and asked how its walk went\")\n"
                f"- `told`: 0-3 short phrases for things about {name} or their world that this {what} tells Pip for the "
                "first time (not anything Pip already knows); empty if nothing is new\n")

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
                              mention: str = "", again: bool = False) -> dict | None:
        task = (
            f"Write as {name}, Pip's neighbor. Who {name} is: {persona}\n"
            + (f"What's already happening in {name}'s life (not news any more): {' '.join(life)}\n" if life else "")
            + self._plans(name, agenda) + self._known(name, told) + (f"{places}\n" if places else "")
            + ("Your letters with Pip so far (oldest first; Pip's in full, yours in brief):\n" + "\n".join(correspondence)
               + "\n" if correspondence else "")
            + (f"\nPip's letter just arrived:\n{received}\n" if received else
               f"\nNo letter is waiting; {name} decides to write to Pip anyway.\n")
            + (f"Pip enclosed something with it: {enclosed}. React to it honestly.\n" if enclosed else "")
            + f"\nWrite {name}'s letter: 2-5 sentences in their own voice, answering what Pip said if anything, and "
            f"sharing something from their own life. Don't reuse a sentence, image or daily ritual from your earlier letters; tell something new."
            + (" Your first try repeated an earlier letter; write it afresh." if again else "") + f" Pip can walk over to visit {name} at home (you can invite it), "
            f"but {name} doesn't go out visiting; letters and the occasional small parcel are the rest. Also report:\n"
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

    async def recall_told(self, name: str, persona: str, said: list[str]) -> list[str] | None:
        task = (
            f"{name} is Pip's neighbor. Who {name} is: {persona}\n"
            f"Everything {name} and Pip have said to each other so far (letters and talk, oldest first):\n"
            + "\n".join(said) + "\n\n"
            f"List what {name} has told Pip about themselves or their world, as `told`: short phrases (under 12 words), "
            "e.g. \"their door rattles in the wind\". At most 20, the ones that stand out most; facts and details, "
            "not greetings or feelings, and nothing that only Pip said."
        )
        out = await self.ask(task, {"told": {"type": "array", "items": {"type": "string"}}}, ["told"], "recall_told")
        return [t for t in out["told"] if isinstance(t, str)] if out and isinstance(out["told"], list) else None

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

    async def narrate_haul(self, place: str, minutes: int, found: list[tuple[str, int]], depleted: bool) -> str | None:
        got = ", ".join(f"{q} {n}" for n, q in found) or "nothing"
        task = (
            f"Pip spent about {minutes} minutes gathering at {place}. What it found (already decided; mention only these, "
            f"invent no other finds): {got}."
            + (" The place is getting picked over, so there was little to find." if depleted else "")
            + " Describe the outing in 1-2 short concrete sentences (under 40 words), second person ('You ...'), in the "
            "manner of someone poking around in this kind of place. No numbers."
        )
        out = await self.ask(task, {"text": {"type": "string"}}, ["text"], "narrate_haul")
        return clip(out["text"], 300) if out else None

    async def design_place(self, place: str, mentions: list[str], existing: list[str]) -> dict | None:
        """Make a place a character told Pip about real, on Pip's first arrival: its kind (from the registry), a
        description that agrees with what was said, what can be found there, and perhaps who lives or works there.
        The engine validates all of it."""
        task = (
            f"Pip has just arrived at {place} for the first time. Nobody has described it before; this is what others "
            "told Pip about it (the place must agree with all of it):\n" + "\n".join(f"- {m}" for m in mentions)
            + f"\n\nDecide what {place} is. `kind`, one of: {place_kinds.gm_lines()}. Use the kind what was said "
            "suggests; a shop only if someone said there's a shop or a trade there. Give:\n"
            "- `description`: 2-3 sentences of the place as Pip finds it (kept, and shown whenever Pip is here)\n"
            "- `blurb`: one short line for a list of places\n"
            "- `loot`: 4-10 things that can be found or had there, each {`name`, `kind`: material, food, seed or tool, "
            "`tier`: common, uncommon or rare, `description`}; include everything the words above say is there. "
            + (f"When a thing is one of these, use its name exactly: {', '.join(existing)}. " if existing else "")
            + "\n- for a shop: `opens` and `closes` (local hours); `gather_help` (a few words: how Pip picks through "
            "the stock), `browse_help` (a few words: how Pip sees what's in), `gerund` (e.g. 'rummaging in the "
            "drawer'). For a wild place or a yard: `gather_help` and `gerund`. A sight needs none of these.\n"
            "- `resident`: someone who lives or works there and will talk with Pip, if the place has one (a shop "
            "normally has its keeper; a wild place or a sight often has nobody): `name`, `persona` (3-5 sentences, "
            "private: who they are, their days, how they talk) and `about` (one short line of what Pip would know of "
            "them once met). If the words above name someone who is there, it's them; never Pip or whoever told Pip "
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

    async def write_happening(self, category: str, tone: str, severity: str, lens: str, line: str, facts: dict, recent: list[str]) -> dict | None:
        """The words for a happening the engine has already decided (see happenings.py): `title` and `text`, written through `lens`."""
        task = (
            f"Write a small event that happens to Pip, who lives alone in a workshop with a garden. Category: {category}. "
            f"Outcome: {tone}. Size: {severity}"
            + (" (a passing moment; keep it in proportion)" if severity == "minor" or tone == "neutral" else "")
            + f". Write it through {lens}: let that feeling colour how it is told, whatever the outcome (a bad turn can still be told with joy).\n"
            + (f"What really changes, which you must not contradict or add to: {line}\n" if line else "Nothing in the world changes: nothing breaks, moves, grows, appears or is lost; it is only a moment.\n")
            + ("It happened in the night, while Pip slept, and Pip finds out on waking: tell it in the past tense.\n" if facts.get("night") else "")
            + f"It is {facts.get('period', 'day')}{' in ' + facts['season'] if facts.get('season') else ''}. Names you may use: {', '.join(facts.get('names') or []) or 'none'}. Do not name anyone else.\n"
            + (f"Something Pip once wrote comes back to mind: \"{facts['memory']}\" Build the moment from it, in your own words.\n" if facts.get("memory") else "")
            + (f"Recent events, so you do not repeat them: {'; '.join(recent)}\n" if recent else "")
            + "Two or three sentences, under 300 characters, second person (you), plain and concrete. Do not mention numbers or objects beyond what really changes, "
            "do not promise anything for later, and do not say how Pip feels or what it should do. Report `title` (a few words) and `text`."
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
            (f"Voice {name}, who Pip meets at {at}." if at else f"Voice {name}, Pip's neighbor.")
            + f" Who {name} is: {persona}\n"
            + (f"Lately in {name}'s life: {' '.join(life)}\n" if life else "")
            + self._plans(name, agenda) + self._known(name, told) + (f"{places}\n" if places else "")
            + (f"What's passed between them recently ({'' if at else 'letters and talk, '}oldest first; Pip's words "
               f"in full, {name}'s earlier ones in brief):\n" + "\n".join(conversation) + "\n" if conversation else "")
            + (f"Right now Pip is at {at}, with {name}." if at else f"Right now Pip is visiting {name} at home.")
            + f" {situation}\n"
            + (f"Pip just said: " + " / ".join(f'"{h}"' for h in heard) + f"\nAnswer Pip as {name}, face to face."
               if heard else f"Pip has just arrived{'' if at else ' at the door'}; greet it as {name} would.")
            + " One or two short sentences, spoken aloud, in character. Most lines need no action; if one helps, a few words in "
            "*asterisks*, never a gesture already used in this talk. Talk like a person, not a teacher: you may ask Pip something, tell your own news "
            "or what you think, disagree, or bring the talk to a close when it has run its course; don't keep giving instructions or say again what "
            "has already been said. "
            f"{name} stays at {at or 'home'} and can't do more than they plausibly could"
            + ("" if can_give else ", and hands Pip nothing: nothing changes hands today, so never describe giving, counting out, "
               "tipping out or letting Pip take or help themselves to anything; if Pip asks for something, say it isn't to be had "
               "today") + f". Report the line as `text`, "
            "and:\n"
            + self._remembering(name, "line") + ("Optional:\n" + self._news("talk") if at else "")
            + (f"- `give`: only if {name} really hands Pip something small right now "
               "(`name`, `kind`: material, seed, food or tool, `qty` 1-3, `description`). Pip receives exactly this and "
               "nothing else, so never describe handing over, offering a pinch of, letting Pip take or help themselves to, or giving anything "
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
