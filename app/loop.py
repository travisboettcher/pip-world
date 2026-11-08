import asyncio
import logging
import os
import random
import time

from . import companions as comp
from . import invented_places as invented
from . import abilities
from . import creations as cr
from . import expectations as exp
from . import gathering
from . import guide
from . import library as lib
from . import memory as mem
from . import neighbors as nb
from . import nightpass as np
from .outreach import Outreach
from . import places
from . import conversation as conv
from . import happenings
from . import market
from . import weather
from . import wishes
from . import worldmap
from . import emotions as emo
from . import sleep as sleepmod
from . import projects as proj
from .config import Settings
from .gm import GameMaster
from .llm.base import LLMBackend, assistant_message
from .pacing import PacingPolicy
from .state import State, clean_sender
from .text import span
from .toolnames import canonical
from .tools import SCOPES, ToolContext, enabled_tools, is_here, specs_for

log = logging.getLogger("agent")
MAX_TOOL_CALLS = 4
EVENT_CONTEXT = 15
DIARY_SHOWN = 4
LIST_SHOWN = 10
LEARNED_SHOWN = 5
HIDDEN_EVENT_KINDS = {"alert", "tick_start"}


DEFAULT_PERSONA = "You are Pip."  # what the agent is told about itself when the deployment supplies no persona


def clock_line(now: float) -> str:
    """The day and time, so a "Thursday at half past four" can be kept."""
    return "It is " + time.strftime("%A %-d %B, %-I:%M %p", time.localtime(now)).replace("AM", "am").replace("PM", "pm") + "."


class Agent:
    def __init__(self, settings: Settings, state: State, backend: LLMBackend, pacing: PacingPolicy,
                 gm_backend: LLMBackend | None = None, rng: random.Random | None = None):
        self.s, self.state, self.backend, self.pacing = settings, state, backend, pacing
        self.tools = enabled_tools(settings)
        self.rng = rng or random.Random()
        self.gm = GameMaster(gm_backend or backend, state)
        self.library = lib.open_library(settings)
        self.outreach = Outreach(settings, state, receive=self.receive)
        emo.attach(state, settings)
        invented.backfill(state)
        invented.backfill_stock(state)
        self.ctx = ToolContext(state, settings, gm=self.gm, rng=self.rng, library=self.library, outreach=self.outreach,
                               vision=bool(getattr(self.backend, "vision", False)))
        self.last_tick = 0.0
        self._wake = asyncio.Event()
        self._force = False
        self._urgent = False
        self._shown_inbox: list[int] = []
        self._budget_logged = False
        self.ticks = 0
        self._moment_shown: dict[int, int] = {}  # event id -> times offered for the diary
        self._reflecting = asyncio.Lock()
        self._told_tries: dict = {}  # neighbors whose told-backfill failed, this run (neighbors.recall_told)
        self._finishing = asyncio.Lock()  # the monitor and a tick may both try to resolve the same session

    # --- wake control ------------------------------------------------
    def receive(self, text: str, sender: str, source: str = "web", conversation: str = "", external_id: str = "") -> int | None:
        """A visitor's message arrives (the web UI, or a channel): queue it, record it and wake Pip. A channel message
        already seen (same source and id) is ignored, so a replay can't answer twice."""
        if external_id and self.state.inbox_has(source, external_id):
            return None
        sender = clean_sender(sender)
        inbox_id = self.state.add_inbox(text, sender, source=source, conversation=conversation, external_id=external_id)
        self.state.log("inbox", id=inbox_id, text=text, sender=sender, **({"source": source, "conversation": conversation}
                                                                          if source != "web" else {}))
        invented.from_chat(self.state, sender, text)  # a visitor can point Pip somewhere new, like a character
        self.request_wake(urgent=True)
        return inbox_id

    def request_wake(self, force: bool = False, urgent: bool = False) -> None:
        """Ask for an early tick. While Pip sleeps only urgent wakes (a visitor) or a forced tick get through."""
        self._force = self._force or force
        self._urgent = self._urgent or urgent
        self._wake.set()

    async def _sleep(self) -> str:
        """Block until the policy says it's time. Returns the wake reason."""
        while True:
            delay = self.pacing.next_delay(time.time(), self.last_tick)
            sess = self.state.session()
            if delay is not None and sess:  # working: no heartbeat until the session ends (events still wake)
                delay = max(delay, sess["ends_at"] - time.time())
            if delay is not None and sleepmod.asleep(self.state):  # asleep: nothing until morning
                delay = max(delay, float(self.state.meta("sleep_until") or 0) - time.time())
            until = self.state.meta("rest_until")
            if delay is not None and until and self.state.agent()["activity"] == "resting":  # resting: sleep through (events still wake)
                delay = max(delay, float(until) - time.time())
            wait = self.state.meta("wait_until")
            if delay is not None and wait and self.state.agent()["activity"] == self.state.meta("wait_label"):  # waiting: left to it (events still wake)
                delay = max(delay, float(wait) - time.time())
            if self._wake.is_set():
                self._wake.clear()
                if self._force:
                    self._force = False
                    self._urgent = False
                    return "forced"
                if self.pacing.wakes_on_events:
                    if sleepmod.asleep(self.state) and not self._urgent:
                        continue  # only a visitor wakes a sleeper; the rest will be there in the morning
                    self._urgent = False
                    wait = self.last_tick + self.s.min_tick_interval - time.time()
                    if wait > 0:
                        await asyncio.sleep(wait)
                    return "event"
                continue  # policy ignores events: go back to waiting
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
            except asyncio.TimeoutError:
                return "timer"

    # --- background tasks --------------------------------------------
    async def run(self) -> None:
        monitor = asyncio.create_task(self._monitor())
        await self.outreach.start()
        try:
            while True:
                reason = await self._sleep()
                try:
                    await self.tick(reason)
                except Exception as e:  # never let one bad tick kill the loop
                    log.exception("tick failed")
                    self.state.log("error", error=f"{type(e).__name__}: {e}")
                    self.last_tick = time.time()
        finally:
            monitor.cancel()
            await self.outreach.stop()

    async def _monitor(self) -> None:
        """Cheap, LLM-free: advance stats, ripen crops, and wake the agent when something needs it."""
        while True:
            await asyncio.sleep(self.s.monitor_seconds)
            try:
                self.check_world()
                await self.resolve_world()
            except Exception:
                log.exception("monitor failed")

    def check_world(self) -> None:
        for alert in self.state.apply_decay():
            self.state.log("alert", stat=alert)
            self.request_wake()
        for crop in self.state.garden_newly_ready():
            self.state.log("garden", plot=crop["plot"], crop=crop["crop"])
            self.request_wake()
        if cr.tick(self.state, self.rng):
            self.request_wake()
        emo.drift(self.state, self.s)
        market.stall_step(self.state, self.s, self.rng)          # customers stop at Pip's stall while it is at the market
        worldmap.sync(self.state, self.s, self.library)  # a new place gets its spot on the map as soon as it exists

    async def resolve_world(self) -> None:
        """World updates that may need the GM (LLM): finished work sessions and projects, companions talking."""
        await weather.refresh(self.state, self.s, time.time())
        if await self.finish_work():
            self.request_wake()
        if await comp.step(self.state, self.s, self.gm, self.rng):
            self.request_wake()
        if await happenings.step(self.state, self.s, self.gm):
            self.request_wake()
        await wishes.share_step(self.state, self.s, self.outreach)
        await nb.ensure_neighbor(self.state, self.s, self.gm, self.rng)
        await nb.recall_told(self.state, self.gm, self._told_tries)
        if await nb.step(self.state, self.s, self.gm, self.rng, library=self.library):
            self.request_wake()
        if mem.due(self.state, self.s, time.time()):
            await self.reflect()

    async def finish_work(self) -> bool:
        """Resolve whatever Pip was busy with once its time is up: work (a finished project becomes a creation),
        a walk (Pip arrives), or reading (Pip takes in what it read)."""
        async with self._finishing:
            sess = self.state.session()
            if not sess or sess["ends_at"] > time.time():
                return False
            if sess["kind"] == "walk":
                return bool(await places.arrive(self.state, self.s, self.gm, self.library, self.rng))
            if sess["kind"] == "read":
                return bool(await lib.finish_reading(self.state, self.s, self.gm, self.library))
            if sess["kind"] == "gather":
                return bool(await gathering.resolve(self.state, self.s, self.gm, self.rng))
            if sess["kind"] == "experiment":
                work = await proj.resolve_experiment(self.state, self.s, self.gm, self.rng)
            else:
                work = await proj.resolve_session(self.state, self.s, self.gm, self.rng)
            if work and work["project_done"]:
                p = self.state.project(work["project_id"])
                c = await cr.make(self.state, self.gm, self.rng, p, proj.level(self.state.skills().get(p["craft"], 0)))
                comp.add_for_creation(self.state, self.rng, c)
            return bool(work)

    async def reflect(self) -> dict | None:
        """Pip's nightly reflection (also triggered by POST /reflect). One at a time."""
        async with self._reflecting:
            started, shown = time.time(), {}
            result = await mem.reflect(self.state, self.s, self.gm, self._system_prompt(), shown_out=shown)
            if result:  # a reflection that found something to go over is followed by the night pass
                try:
                    await np.run(self.state, self.s, self.gm, self._system_prompt(), result, shown, tuple(self.tools),
                                 since_ts=started)
                except Exception as e:  # never let it break the reflection
                    log.exception("night pass failed")
                    self.state.log("error", error=f"night pass: {type(e).__name__}: {e}")
            return result

    # --- one tick ----------------------------------------------------
    async def tick(self, reason: str) -> None:
        """One wake. A visitor message Pip read but never answered gets one more look (see _second_chance)."""
        started, self._shown_inbox = time.time(), []
        try:
            await self._tick(reason)
        finally:
            self._second_chance(started)

    def _second_chance(self, started: float) -> None:
        """Pip is told a visitor can only hear it through `say`, but a model busy with its work sometimes forgets.
        A message that got no `say` is put back once, plainly marked; a second silence is respected."""
        if not self._shown_inbox:
            return
        said = {i for e in self.state.events_since(started - 1) if e["kind"] == "say" for i in e["data"].get("to", [])}
        again = False
        for row in self.state.inbox_rows(self._shown_inbox):
            if row["id"] not in said and not row["gift"] and not row["offers"]:
                self.state.reoffer_inbox(row["id"])
                again = True
        if again:
            self.request_wake()

    async def _tick(self, reason: str) -> None:
        """One wake: up to max_calls_per_tick LLM calls.

        The first call always happens; further calls happen only when a tool result
        asks for a follow-up (ToolResult.followup), so the model can use fresh
        information immediately. Anything still pending when the call cap or the
        daily budget is hit is left for the next tick (and an early wake is requested).
        """
        self.last_tick = time.time()
        self.state.apply_decay()
        sleepmod.wake_up(self.state)
        await self.finish_work()  # the heartbeat can land right as a session ends: show its result now

        inbox = self.state.pending_inbox()
        self.ctx.visitor_ids = [m["id"] for m in inbox]
        messages: list[dict] = [{"role": "user", "content": self._perception(reason, inbox)}]
        specs = self._specs()
        if not self.ctx.vision:  # nothing to look with
            specs = [sp for sp in specs if sp.name != "look"]
        if not self.outreach.can_send():  # a postcard is only offered when one could actually go out
            specs = [sp for sp in specs if sp.name != "send_postcard"]

        for step in range(max(1, self.s.max_calls_per_tick)):
            if self.state.budget_exceeded():
                if not self._budget_logged:
                    self.state.log("budget_exceeded", **self.state.usage_today())
                    self._budget_logged = True
                if step:
                    self.request_wake()  # follow-up is waiting on budget
                return
            self._budget_logged = False

            await self.outreach.typing([m["id"] for m in inbox])  # "typing..." wherever Pip is about to answer
            resp = await self.backend.complete(
                system=self._system_prompt(), messages=messages, tools=specs,
                max_tokens=self.s.llm_max_tokens,
            )
            self.state.add_usage(resp.usage.input_tokens, resp.usage.output_tokens)
            if step == 0:
                self.state.consume_inbox([m["id"] for m in inbox])
                self._shown_inbox = [m["id"] for m in inbox]
                if inbox:
                    self.state.log("inbox_read", ids=[m["id"] for m in inbox])
                self.ticks += 1
            self.state.log("tick", reason=reason, step=step, text=resp.text,
                           tokens=resp.usage.input_tokens + resp.usage.output_tokens,
                           tools=[c.name for c in resp.tool_calls])
            if inbox and resp.text:  # plain-text reply (the `say` tool is the reliable path)
                self.state.log("say", text=resp.text, to=[m["id"] for m in inbox])
                await self.outreach.route_reply(resp.text, [m["id"] for m in inbox])
            if not resp.tool_calls:
                return

            results = [await self._run_tool(c, i) for i, c in enumerate(resp.tool_calls)]
            if not any(r["followup"] for r in results):
                return
            if step + 1 >= self.s.max_calls_per_tick:
                self.request_wake()  # results are in the event log; digest them next tick
                return
            messages.append(assistant_message(resp))
            messages.append({"role": "tool", "results": results})

    async def _run_tool(self, call, index: int) -> dict:
        """Execute one tool call. Always returns a result dict (errors are results too)."""
        out = {"id": call.id, "name": call.name, "followup": False, "is_error": False}
        entry = self.tools.get(canonical(call.name))
        if index >= MAX_TOOL_CALLS:
            out.update(content="skipped: too many tool calls this turn", is_error=True)
        elif not entry:
            self.state.log("tool_error", tool=call.name, error="unknown or disabled tool")
            out.update(content=f"error: unknown or disabled tool {call.name!r}", is_error=True, followup=True)
        else:
            try:
                result = await entry[1](self.ctx, call.arguments)
            except Exception as e:
                self.state.log("tool_error", tool=call.name, args=call.arguments,
                               error=f"{type(e).__name__}: {e}")
                out.update(content=f"error: {type(e).__name__}: {e}", is_error=True, followup=True)
            else:
                self.state.log("tool", tool=call.name, args=call.arguments, result=result.text,
                               **({"noop": True} if result.noop else {}))
                out.update(content=result.text, followup=result.followup,
                           **({"images": result.images} if result.images and self.backend.vision else {}))
        return out

    def _system_prompt(self) -> str:
        """Who the agent is (the deployment's optional persona file, re-read every time; by default just a name) followed by how the world works
        (the guide, built from what is enabled)."""
        persona = ""
        if os.path.exists(self.s.persona_path):
            with open(self.s.persona_path) as f:
                persona = f.read().strip()
        return (persona or DEFAULT_PERSONA) + "\n\n" + guide.render(self.tools, self.s, self.library is not None)

    def _talk(self, inbox: list[dict]) -> list[str]:
        """The conversations Pip is in, in full: a visit under way, and the chat so far with each visitor who is waiting for an answer."""
        now, lines = time.time(), []
        here = self.state.agent()["location"]
        for ch in self.state.characters("neighbor"):
            if places.home_of(ch) == here and (said := conv.visit_lines(self.state, ch["name"], float(self.state.meta("arrived_at") or 0))):
                lines += [f"Talking with {ch['name']} (this visit, oldest first):"] + [f"  {l}" for l in said]
        waiting = {m["id"] for m in inbox}
        for sender in dict.fromkeys(m["sender"] for m in inbox if not m["gift"]):
            if said := conv.thread_lines(self.state, sender, now, skip_ids=waiting):
                lines += [f"Your conversation with {sender} so far (oldest first):"] + [f"  {l}" for l in said]
        return lines

    def _belongings(self) -> list[str]:
        lines: list[str] = []
        if "use_item" in self.tools:
            items = self.state.items()
            lines.append("Your belongings:")
            lines += [f"- {i['name']} x{i['qty']} ({i['kind']})" + (f": {i['description']}" if i["description"] else "")
                      for i in items] or ["- (nothing)"]
        if any(t in self.tools for t in ("buy", "sell", "pay")):
            lines.append(f"Coins: {self.state.coins()}")
            lines += market.stall_lines(self.state, self.state.agent()["location"], time.time())
        if "plant" in self.tools:
            lines.append("Your garden:")
            for g in self.state.garden():
                if g["state"] == "empty":
                    lines.append(f"- plot {g['plot']}: empty")
                elif g["state"] == "ready":
                    lines.append(f"- plot {g['plot']}: {g['crop']} are RIPE - harvest them")
                else:
                    lines.append(f"- plot {g['plot']}: {g['crop']} growing, ready in about {span(g['ready_in_min'])}")
        return lines

    def _projects(self) -> list[str]:
        if "work_on" not in self.tools:
            return []
        active = self.state.projects("active")
        sess = self.state.session()
        lines = ["Your projects:"]
        for p in active:
            i = proj.current_stage(p)
            line = f"- #{p['id']} {p['name']} ({p['craft']}, difficulty {p['difficulty']}/5): {proj.percent(p)}% done"
            if i is not None:
                st = p["stages"][i]
                line += f", now on stage {i + 1}/{len(p['stages'])} '{st['name']}'"
                if st["materials"]:
                    needs = ", ".join(f"{q} {n}" for n, q in st["materials"].items())
                    if st["started"]:
                        line += f" (its {needs} are already in hand)"
                    else:
                        take, missing = proj.missing_materials(self.state, st)
                        have = {t["name"] for t, _ in take}
                        hints = [f"you found {n} at {places.label(f['place'])}" for n in st["materials"] if n not in have
                                 for f in self.state.found_where(n)[:1]]
                        line += f" (needs {needs}" + (f"; missing {', '.join(missing)}" if missing else "; you have them")
                        line += (f" - {'; '.join(hints)}" if hints else "") + ")"
                later = proj.upcoming_needs(p, i + 1)
                if later:
                    line += "; later stages need " + ", ".join(
                        f"{q} {n} (you have {self.state.find_item(n)[0]['qty'] if self.state.find_item(n)[0] else 0})"
                        for n, q in later.items())
            elif proj.crossroads(p):
                line += ", all you know to do is done - the way forward isn't clear yet"
            if sess and sess["kind"] in ("work", "experiment") and sess["project_id"] == p["id"]:
                line += f" - you're {'experimenting on' if sess['kind'] == 'experiment' else 'working on'} it now, about {max(1, round((sess['ends_at'] - time.time()) / 60))} min left"
            lines.append(line)
            if p["questions"]:
                lines.append("  you don't know yet: " + "; ".join(p["questions"]))
            if p["findings"]:
                lines.append("  you've found out: " + "; ".join(p["findings"][-4:]))
        if not active:
            lines.append("- (none - start_project when you want to make something)")
        held = self.state.projects("paused")
        if held:
            lines.append("On hold (resume_project to pick one back up): " + ", ".join(p["name"] for p in held))
        lines += proj.feel(self.state)
        made = self.state.creations()
        if made:
            lines.append("Things you've made:")
            lines += [cr.describe(c) for c in made]
        return lines

    @staticmethod
    def _moment_text(e: dict) -> str | None:
        """One-line description of an event worth a diary entry, or None for ordinary events."""
        d, k = e["data"], e["kind"]
        if k == "gift":
            return f"{d['sender']} gave you {d['qty']} x {d['item']}"
        if k == "garden":
            return f"Your {d['crop']} in plot {d['plot']} ripened"
        if k == "reading" and d.get("finished"):
            return f"You finished reading {d['title']}"
        if k == "arrived" and d.get("first_time") and d["place"] != places.HOME:
            return f"You went to {places.label(d['place'])} for the first time"
        if k == "creation_made":
            return f"Your {d['project']} became {d['name']}: {d['description']}"
        if k == "work" and not d.get("interrupted"):
            if d["project_done"]:
                return f"You finished {d['project']}! {d['text']}"
            if (d["result"] in ("breakthrough", "setback", "blowup") or d["finished_stage"] or d.get("learned")
                    or d.get("expectation")):
                done = " (that stage is done)" if d["finished_stage"] else ""
                done += f" ({d['step_note']})" if d.get("step_note") else ""
                done += f" ({d['expectation']})" if d.get("expectation") else ""
                lost = f" You lost some {', '.join(d['lost'])}." if d.get("lost") else ""
                learned = f" You learned: {d['learned']}" if d.get("learned") else ""
                return f"Working on {d['project']}: {d['text']}{done}{lost}{learned}"
        if k == "experiment" and not d.get("interrupted"):
            extra = (f" You now know: {d['finding']}" if d.get("finding") else "") + (
                " New steps opened up: " + ", ".join(d["added"]) + "." if d.get("added") else "")
            note = f" ({d['expectation']})" if d.get("expectation") else ""
            return f"Experiment on {d['project']} ({d['hypothesis']}): {d['text']}{extra}{note}"
        if k == "tool":
            t, a, r = d["tool"], d["args"], str(d.get("result", ""))
            if t == "plant" and r.startswith("planted"):
                return r.capitalize()
            if t == "harvest" and r.startswith("harvested"):
                return r.capitalize()
            if t == "start_project" and r.startswith("started project"):
                return f"You started a new project: {a.get('name')}"
            if t == "resolve_note" and r.startswith("crossed off"):
                return f"You crossed off #{a.get('id')}" + (f": {a['outcome'][:100]}" if a.get("outcome") else "")
        return None  # visitor messages are summarised separately in _moments

    def _gallery(self) -> list[str]:
        """The last few pictures and pieces, by number, so Pip can send or refer to them."""
        if "draw" not in self.tools and "write_piece" not in self.tools:
            return []
        works = self.state.works(limit=4)
        return (["Your gallery (latest):"] + [f"- #{w['id']} {w['title']} ({'drawing' if w['kind'] == 'drawing' else 'writing'})"
                                              for w in works]) if works else []

    def _calibration(self) -> list[str]:
        """How close Pip's predictions have been, in plain counts (only once there are enough to count)."""
        rows = self.state.expectations(limit=60)
        lines = exp.calibration(rows)
        if lines:
            by_craft: dict[str, list[float]] = {}
            for r in rows:
                if r["kind"] in ("session", "experiment"):
                    by_craft.setdefault(r["craft"] or "your work", []).append(abs(r["error"]))
            lines += [f"Your misses on {c} (average distance from what you expected): {a} before, {b} lately."
                      for c, a, b in exp.learning_progress(by_craft) if abs(a - b) >= 0.5]
        return lines

    def _firsts(self) -> list[str]:
        """Things that happened for the first time recently, as plain facts (shown a few ticks, then dropped)."""
        found = self.state.recent_firsts(self.s.firsts_max_age_hours, self.s.firsts_showings, self.s.firsts_shown)
        if not found:
            return []
        self.state.mark_firsts_shown([f["key"] for f in found])
        return ["New for you:"] + [f"- {f['label']} ({mem.ago(f['first_ts'])})" for f in found]

    def _moments(self) -> list[str]:
        """Notable things since Pip's last diary entry, offered a few times so they aren't forgotten.

        Deterministic about *when* something is worth a diary line; Pip decides what (if anything) to write.
        """
        if "note_to_self" not in self.tools:
            return []
        last = self.state.memories("diary", limit=1)
        since = max(time.time() - self.s.moment_window_minutes * 60, last[0]["ts"] if last else 0)
        moments, visit_ids, visitors, visit_inbox = [], [], [], []
        window = self.state.events_since(since)
        said_to = {i for e in window if e["kind"] == "say" for i in e["data"].get("to", [])}
        for e in window:  # oldest first
            if self._moment_shown.get(e["id"], 0) >= self.s.moment_showings:
                continue
            if e["kind"] == "inbox" and e["data"].get("letter"):
                moments.append(([e["id"]], f"A letter came from {e['data']['sender']}"))
            elif e["kind"] == "inbox":
                visit_ids.append(e["id"])  # never quote visitor text here: Pip would answer it again
                visit_inbox.append(e["data"].get("id"))
                who = e["data"].get("sender") or "A visitor"
                if who not in visitors:
                    visitors.append(who)
            elif text := self._moment_text(e):
                moments.append(([e["id"]], text))
            elif majors := [f["label"] for f in e["data"].get("firsts", []) if f["tier"] == "major"]:
                moments.append(([e["id"]], majors[0].capitalize()))
        if visit_ids:
            n = len(visit_ids)
            who = " and ".join(visitors) if visitors else "A visitor"
            replied = all(i in said_to for i in visit_inbox)
            moments.insert(0, (visit_ids, f"{who} came by and talked with you ({n} message{'s' if n != 1 else ''}; "
                                          + ("you already replied, don't answer again)" if replied else
                                             "you haven't said anything back to them yet - only `say` is heard)")))
        moments = moments[-5:]
        for ids, _ in moments:
            for event_id in ids:
                self._moment_shown[event_id] = self._moment_shown.get(event_id, 0) + 1
        if not moments:
            return []
        return ["Since you last wrote in your diary, this happened:"] + [f"- {text}" for _, text in moments] + \
               ["If any of it mattered to you, write a short diary entry now about how it felt "
                "(note_to_self, section diary) - in your own voice, not a list of facts. If none of it did, skip it."]

    def _journal(self) -> list[str]:
        def fmt(m): return f"- #{m['id']} {m['text'][:200]}"
        belongings = self.state.items()

        def fmt_wish(m):
            # items received since the wish was last written/edited, so editing or resolving silences this
            since = m["edited_at"] or m["ts"]
            got = [i["name"] for i in belongings if i["ts"] > since and State.related(i["name"], m["text"])]
            note = (f"  [you've since received: {', '.join(got)} - is this wish met? resolve_note it, or "
                    "edit_note it down to what's still missing]") if got else ""
            if m.get("kind") in ("", "thing"):
                where = wishes.sources(self.state, m["text"], time.time())
            else:
                where = wishes.doings(self.state, self.s, self.library, m["text"], self.tools)
            if where:
                note += f"  [you could try: {'; '.join(where)}]"
            return fmt(m) + note

        visits = [(c["name"], ts) for c in self.state.characters("neighbor")
                  if (ts := self.state.last_arrived(places.home_of(c)))]

        heard_of = [r for r in invented.records(self.state) if r["status"] == "heard"]

        def fmt_todo(m):
            # a neighbor visited since the to-do was written: the visit may have been the to-do
            since = m["edited_at"] or m["ts"]
            went = [name for name, ts in visits if ts > since and State.related(name, m["text"])]
            note = (f"  [you've since visited {', '.join(went)} - is this done? resolve_note it, or edit_note it down "
                    "to what's left]") if went else ""
            for r in invented.named_in(heard_of, m["text"]):  # somewhere Pip has only heard of: it can go
                note += (f"  [{places.label(r['key'])}: you've heard of it; go_to {r['key']} to walk there]"
                         if r["walk_minutes"] is not None else
                         f"  [{places.label(r['key'])}: you've heard of it, but it's too far to walk]")
            return fmt(m) + note
        lines: list[str] = []
        diary = self.state.memories("diary", limit=DIARY_SHOWN)
        lines += ["Your diary (latest entries):"] + [fmt(m) for m in diary] if diary else ["Your diary is empty."]
        for section, label, hint in (
            ("todo", "Your to-do list (open)", "nothing planned - anything you'd like to get done?"),
            ("wishlist", "Your wishlist (open)", "nothing yet - what do you want?"),
            ("ambitions", "Your ambitions (open)", "none yet - what would you like to achieve?"),
        ):
            items = self.state.memories(section, status="open", limit=LIST_SHOWN)
            show = {"wishlist": fmt_wish, "todo": fmt_todo}.get(section, fmt)
            lines += [f"{label}:"] + ([show(m) for m in items] if items else [f"- ({hint})"])
        learned = self.state.memories("learned", limit=LEARNED_SHOWN)
        if learned:
            lines += ["Things you've learned:"] + [fmt(m) for m in learned]
        return lines

    def _specs(self) -> list:
        """The tools to offer now: what can be done here, described for here. Mid-walk Pip is nowhere yet, so only what works anywhere."""
        if places.present_at(self.state) is None:
            return specs_for(self.tools, "")
        here = places.here(self.state, self.s, self.library)
        return specs_for(self.tools, here.key, here, places.open_now(here, self.s))

    def _perception(self, reason: str, inbox: list[dict]) -> str:
        a = self.state.agent()
        lines = [
            f"Woke because: {reason}",
            f"State: hunger {a['hunger']:.2f} (1=starving), energy {a['energy']:.2f} (0=exhausted), "
            f"mood {a['mood']}, location {a['location']}, activity {a['activity']}"
            + (f" ({a['description']})" if a["description"] else ""),
            clock_line(time.time()),
        ]
        if "sleep" in self.tools:
            lines += sleepmod.perception(self.state, self.s, time.time())
        lines += abilities.perception(self.state, time.time())
        lines += weather.perception(self.state, self.s, time.time())
        lines += emo.perception(self.state, self.s)
        lines += self._firsts()
        lines += self._calibration()
        lines += places.perception(self.state, self.s, self.library)
        lines += mem.perception(self.state)
        lines += np.perception(self.state, self.s)
        lines += self.outreach.perception()
        lines += self._gallery()
        lines += happenings.perception(self.state, self.tools, time.time()) if self.s.happenings != "off" else []
        lines += self._belongings()
        lines += self._projects()
        lines += nb.perception(self.state)
        lines += lib.perception(self.state, self.library)
        lines += self._journal()
        events = [e for e in reversed(self.state.events(EVENT_CONTEXT * 2)) if e["kind"] not in HIDDEN_EVENT_KINDS]
        if events:
            lines.append("Recent events:")
            for e in events[-EVENT_CONTEXT:]:
                d = e["data"]
                if e["kind"] == "tick":
                    if d.get("text"):
                        lines.append(f"- you said/thought: {d['text']}")
                elif e["kind"] == "tool":
                    if d.get("noop"):
                        continue
                    lines.append(f"- you used {d['tool']}({d['args']}) -> {d['result']}")
                elif e["kind"] == "creation":
                    lines.append(f"- {d['text']}" if d["what"] in ("stopped", "helper", "used")
                                 else f"- your {d['name']}: {d['text']}")
                elif e["kind"] == "gathered":
                    lines.append(f"- {d['text']}" + (" (you cut it short)" if d.get("interrupted") else ""))
                elif e["kind"] == "woke":
                    lines.append(f"- {sleepmod.woke_text(d)}")
                elif e["kind"] == "reading":
                    lines.append(f"- you read {d['title']}" + (f" (now {d['percent']}% through)" if not d["finished"]
                                                                else " (and finished it)") + f": {d['summary']}"
                                 + "".join(f' "{q}"' for q in d.get("quotes", [])))
                elif e["kind"] == "arrived":
                    lines.append(f"- you arrived at {places.label(d['place'])}" if d["place"] != places.HOME
                                 else "- you got home")
                elif e["kind"] == "letter_sent":
                    lines.append(f"- you wrote to {d['to']}: {d['text'][:200]}"
                                 + (f" (enclosed: {d['enclosed']})" if d.get("enclosed") else ""))
                elif e["kind"] == "outreach" and d.get("what") == "postcard" and d.get("delivered"):
                    lines.append(f"- you sent a postcard ({d.get('channel')}): {d['text']}")
                elif e["kind"] == "stall_sale":
                    lines.append(f"- at your stall you sold {d['qty']} {d['item']} for {market.coins_text(d['coins'])}")
                elif e["kind"] == "heard_of_place":
                    lines.append(f"- {d['by']} told you about {places.label(d['place'])}"
                                 + (f": {d['there']}" if d["there"] else ""))
                elif e["kind"] == "companion":  # model-written, so quoted like a visitor's words
                    lines.append(f"- {d['name']} said: \"{d['text']}\"" + (" (answering you)" if d.get("reply") else ""))
                elif e["kind"] == "creation_made":
                    lines.append(f"- you finished making {d['name']} ({d['quality']}): {d['description']}")
                elif e["kind"] == "experiment":
                    lines.append(f"- experiment on {d['project']} ({d['hypothesis']}): {d['outcome']}"
                                 + ("" if d.get("interrupted") else f" - {d['text']}")
                                 + (f" [learned: {d['finding']}]" if d.get("finding") else "")
                                 + (f" [{d['expectation']}]" if d.get("expectation") else ""))
                elif e["kind"] == "work":
                    lines.append(f"- work on {d['project']} ({d['stage']}): {d['result']}"
                                 + ("" if d.get("interrupted") else f" - {d['text']}")
                                 + (f" [learned: {d['learned']}]" if d.get("learned") else "")
                                 + (f" [{d['expectation']}]" if d.get("expectation") else "")
                                 + (f" [{d['step_note']}]" if d.get("step_note") else "")
                                 + (" [project finished!]" if d["project_done"] else
                                    " [stage done]" if d["finished_stage"] else f" [{d['percent']}% done]"))
        def visitor(m):
            if m["gift"]:
                return f"- {m['text']}"
            via = f" (via {m['source']})" if m.get("source", "web") != "web" else ""
            return f"- {m['sender']}{via}: {m['text']}"
        lines += self._talk(inbox)
        fresh, again = [m for m in inbox if not m.get("offers")], [m for m in inbox if m.get("offers")]
        if fresh:
            lines.append("Inbox (visitors) - they only hear you if you use `say`:")
            lines += [visitor(m) for m in fresh]
        if again:
            lines.append("A visitor wrote earlier and you haven't answered (use `say` if you'd like to; silence is fine too):")
            lines += [visitor(m) for m in again]
        lines += self._moments()  # last, so it is the freshest thing in the prompt
        return "\n".join(lines)
