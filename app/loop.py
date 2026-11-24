import asyncio
import contextlib
import logging
import os
import random
import time
from dataclasses import replace

from . import invented_places as invented
from . import abilities
from . import creations as cr
from . import expectations as exp
from . import guide
from . import world_pack
from . import library as lib
from . import memory as mem
from . import builder
from . import calendar
from . import becoming
from . import layouts
from . import looks
from . import modules
from . import sources
from . import neighbors as nb
from . import others
from . import nightpass as np
from .outreach import Outreach
from . import places
from . import conversation as conv
from . import happenings
from . import reminders, talk
from . import wishes
from . import worldmap
from . import emotions as emo
from . import sleep as sleepmod
from . import stakes
from .config import Settings
from .gm import GameMaster
from .llm.base import LLMBackend, assistant_message
from .pacing import PacingPolicy
from .state import State, clean_sender, world_path
from .text import clip, coins_text, span
from .toolnames import canonical
from .tools import SCOPES, ToolContext, enabled_tools, is_here, module_specs, module_tool, specs_for
from . import stats as stats_mod

log = logging.getLogger("agent")
MAX_TOOL_CALLS = 4
EVENT_CONTEXT = 15
DIARY_SHOWN = 4
LIST_SHOWN = 10
LEARNED_SHOWN = 5
HIDDEN_EVENT_KINDS = {"alert", "tick_start", "reminded", "faded"}




FREE_MINUTES = 120     # nothing due for this long is free time
FREE_SHOWN = 2


def clock_line(now: float) -> str:
    """The day and time, so a "Thursday at half past four" can be kept."""
    return "It is " + time.strftime("%A %-d %B, %-I:%M %p", time.localtime(now)).replace("AM", "am").replace("PM", "pm") + "."


class World:
    """The world one engine runs (docs/DESIGN-multi-agent.md): the pack, the narrator, the library and the module runner its agents share,
    and the world's own steps (modules, layouts, the map), run once a beat whatever the number of agents. It is its agents' supervisor:
    each runs its own loop, and one whose loop dies is started again without stopping the world or the others. Until the world has a
    handle of its own (release 3) its steps act through its first agent's State, which has the world's file attached."""

    def __init__(self, settings: Settings, backend: LLMBackend, state: State):
        self.s, self.state = settings, state
        self.pack = world_pack.load(settings)
        world_pack.set_active(self.pack)                     # one engine runs one world: what has no settings at hand asks world_pack.active()
        self.gm = GameMaster(backend, state, system=self.pack.narrator_system())     # of whichever agent it works for now
        self.library = lib.open_library(settings)
        self.runner = modules.runner_for(settings)
        self.agents: list["Agent"] = []
        self.talks: dict[frozenset, asyncio.Task] = {}          # the talks between its agents going on now (Agent._hold_talk), by the pair's keys
        others.use(self)                                       # who else lives here, for code acting as one of them
        sources.wire(self)                                     # the books and the like modules may ask (sources.py)

    def wake(self) -> None:
        for a in self.agents:
            a.request_wake()

    def talking_with(self, agent: "Agent") -> "Agent | None":
        """Who the agent is in a talk with just now, if anyone."""
        pair = next((p for p, t in self.talks.items() if agent.identity.key in p and not t.done()), None)
        return next((a for a in self.agents if pair and a is not agent and a.identity.key in pair), None)

    def check(self) -> None:
        for a in self.agents:                                 # a new place gets its spot on the map as soon as it exists, whoever's it is
            with a.acting():
                worldmap.sync(a.state, self.s, self.library)
        if not self.agents:
            worldmap.sync(self.state, self.s, self.library)

    async def step(self) -> None:
        """The world's updates, once a beat: the modules it ships, their calls and answers and what they say happens, the owner told of
        them, places laid out. Anything that happened wakes the agents."""
        await modules.offer_library(self.state, self.s, self.runner, things=False)      # a creation's workings are its agent's to offer
        woke = await modules.step(self.state, self.s, self.runner, scope="world")
        woke = await modules.answer(self.state, self.s, self.gm, self.runner, scope="world") or woke     # the model's words they asked for
        woke = await happenings.from_modules(self.state, self.s, self.gm, scope="world") or woke        # what they said happens
        if self.agents:
            await modules.notify_owner(self.state, self.s, self.agents[0].outreach)       # the owner's channel is the first agent's for now
        for a in self.agents or [None]:                        # build (or rebuild) places laid out by modules: every agent's (a home of its own)
            with (a.acting() if a else contextlib.nullcontext()):
                await layouts.step(a.state if a else self.state, self.s, self.runner, library=self.library)
        others.deliver()                                       # letters between agents that are due (each wakes its reader)
        if woke:
            self.wake()

    async def night(self) -> None:
        """The world's own turn at night, after an agent's reflection (once a world night): perhaps one new rule (builder.py), seeing
        every agent, as the world (its first agent), whoever's reflection it follows."""
        first = self.agents[0] if self.agents else None
        try:
            with first.acting() if first else contextlib.nullcontext():
                await builder.night(self.state, self.s, self.gm, self.runner, agents=[(a.identity, a.state) for a in self.agents] or None)
        except Exception as e:
            log.exception("builder failed")
            self.state.log("error", error=f"builder: {type(e).__name__}: {e}")

    async def run(self) -> None:
        """Supervise: every agent's loop, started again (and said, in its own log) if it dies; the world's steps every beat."""
        tasks = {a: asyncio.create_task(a.run()) for a in self.agents}
        try:
            while True:
                await asyncio.sleep(self.s.monitor_seconds)
                for a, t in list(tasks.items()):
                    if t.done() and not t.cancelled():
                        e = t.exception()
                        a.state.log("error", error=f"the agent's loop stopped ({type(e).__name__}: {e}); started again" if e
                                    else "the agent's loop stopped; started again")
                        tasks[a] = asyncio.create_task(a.run())
                try:
                    self.check()
                    await self.step()
                except Exception:
                    log.exception("world step failed")
        finally:
            for t in tasks.values():
                t.cancel()


def build(settings: Settings, backend: LLMBackend, gm_backend: LLMBackend | None = None) -> World:
    """The world the settings choose, with its agents (AGENTS, else all of the pack's), each with its own file (the first agent's is
    DB_PATH, the others' agents/<key>.db beside it), the world's file shared, its own budget (DAILY_TOKEN_BUDGET_<KEY>) and pacing.
    Only the first of the pack's agents has the deployment's persona file and reaches the owner (outreach)."""
    from .pacing import get_policy
    pack = world_pack.load(settings)
    world_pack.set_active(pack)                         # before any State: a State reads the world it starts in
    keys = [a.key for a in pack.agents]
    unknown = [k for k in settings.agents or [] if k not in keys]
    if unknown:
        raise ValueError(f"AGENTS names {', '.join(unknown)}, which this world doesn't have (it has {', '.join(keys)})")
    world = None
    for key in [k for k in keys if settings.agents is None or k in settings.agents]:
        first = key == pack.agent.key
        s = replace(settings, agent_key=key, world_db_path=world_path(settings),
                    db_path=settings.db_path if first else os.path.join(os.path.dirname(settings.db_path), "agents", f"{key}.db"),
                    daily_token_budget=settings.agent_budgets.get(key, settings.daily_token_budget),
                    persona_path=settings.persona_path if first else "", outreach=settings.outreach if first else "off")
        os.makedirs(os.path.dirname(s.db_path) or ".", exist_ok=True)
        world = Agent(s, State(s), backend, get_policy(s), gm_backend=gm_backend, world=world).world
    looks.gather_scenes(world.agents)                   # each place looks one way to everyone: the world's
    others.acquainted(world.agents)                     # neighbours know each other from the start
    becoming.step(world.agents)                         # an agent that was a character takes over from them, once
    return world


class Agent:
    def __init__(self, settings: Settings, state: State, backend: LLMBackend, pacing: PacingPolicy,
                 gm_backend: LLMBackend | None = None, rng: random.Random | None = None, world: World | None = None):
        self.s, self.state, self.backend, self.pacing = settings, state, backend, pacing
        self.tools = enabled_tools(settings)
        self.rng = rng or random.Random()
        self.world = world or World(settings, gm_backend or backend, state)     # alone, an agent has a world of its own
        self.world.agents.append(self)
        self.identity = state.identity()                                         # which of the world's agents this is
        self.outreach = Outreach(settings, state, receive=self.receive)
        emo.attach(state, settings)
        invented.backfill(state)
        invented.backfill_stock(state)
        self.ctx = ToolContext(state, settings, gm=self.gm, rng=self.rng, library=self.library, outreach=self.outreach,
                               vision=bool(getattr(self.backend, "vision", False)), runner=self.runner)
        self.last_tick = 0.0
        self._wake = asyncio.Event()
        self.talking = asyncio.Lock()                        # held for a turn, or while another agent talks with this one
        self._force = False
        self._urgent = False
        self._shown_inbox: list[int] = []
        self._budget_logged = False
        self.ticks = 0
        self._moment_shown: dict[int, int] = {}  # event id -> times offered for the diary
        self._reflecting = asyncio.Lock()
        self._told_tries: dict = {}  # neighbors whose told-backfill failed, this run (neighbors.recall_told)
        self._finishing = asyncio.Lock()  # the monitor and a tick may both try to resolve the same session

    # --- what the world shares (a narrator, runner or library swapped on an agent is its world's) ----------------------------------
    pack = property(lambda self: self.world.pack)
    gm = property(lambda self: self.world.gm, lambda self, v: setattr(self.world, "gm", v))
    runner = property(lambda self: self.world.runner, lambda self, v: setattr(self.world, "runner", v))
    library = property(lambda self: self.world.library, lambda self, v: setattr(self.world, "library", v))

    # --- wake control ------------------------------------------------
    def receive(self, text: str, sender: str, source: str = "web", conversation: str = "", external_id: str = "",
                wake: bool = True) -> int | None:
        """A visitor's message arrives (the web UI, or a channel): queue it, record it and wake the agent (unless `wake` is False: it
        waits for the agent's next turn). A channel message already seen (same source and id) is ignored, so a replay can't answer twice."""
        if external_id and self.state.inbox_has(source, external_id):
            return None
        sender = clean_sender(sender)
        inbox_id = self.state.add_inbox(text, sender, source=source, conversation=conversation, external_id=external_id)
        self.state.log("inbox", id=inbox_id, text=text, sender=sender, **({"source": source, "conversation": conversation}
                                                                          if source != "web" else {}))
        invented.from_chat(self.state, sender, text)  # a visitor can point the agent somewhere new, like a character
        if wake:
            self.request_wake(urgent=True)
        return inbox_id

    def request_wake(self, force: bool = False, urgent: bool = False) -> None:
        """Ask for an early tick. While the agent sleeps only urgent wakes (a visitor) or a forced tick get through."""
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
            if delay is not None and self.world.talking_with(self):  # talking: no heartbeat until the talk is over (events still wake)
                delay = None
            if self._wake.is_set():
                self._wake.clear()
                if self._force:
                    self._force = False
                    self._urgent = False
                    return "forced"
                if self.pacing.wakes_on_events:
                    if sleepmod.asleep(self.state) and (not self._urgent or stakes.out(self.state)):
                        continue  # only a visitor wakes a sleeper (not one out cold); the rest will be there in the morning
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
    def acting(self):
        """Whatever runs now runs as this agent: it is the one named, and the narrator spends from its State (world_pack.acting)."""
        return world_pack.acting(self.identity, self.state)

    async def run(self) -> None:
        with self.acting():                                      # the monitor below, a task of this one, acts as this agent too
            await self._run()

    async def _run(self) -> None:
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
        """Cheap, LLM-free: advance the agent's stats, and wake it when something needs it (the world's steps are its World's)."""
        while True:
            await asyncio.sleep(self.s.monitor_seconds)
            try:
                self.check()
                await self.step()
            except Exception:
                log.exception("monitor failed")

    def check(self) -> None:
        for alert in self.state.apply_decay():
            self.state.log("alert", stat=alert)
            self.request_wake()
        if calendar.step(self.state, self.s, self.library):             # time to set off for a commitment (asleep: at waking)
            self.request_wake()
        emo.drift(self.state, self.s)

    def check_world(self) -> None:
        """The agent's checks and its world's (one agent alone)."""
        self.check()
        self.world.check()

    async def resolve_world(self) -> None:
        """The world's steps, then the agent's (one agent alone: as the monitors run them)."""
        await self.world.step()
        await self.step()

    async def step(self) -> None:
        """The agent's own updates that may need the narrator: a stat run out, a walk or session ended, its happenings, wishes shared,
        the letters people write to it, its reflection at night."""
        with self.acting():
            await self._step()

    async def _step(self) -> None:
        await modules.offer_library(self.state, self.s, self.runner, rules=False)     # its creations' workings
        if await modules.step(self.state, self.s, self.runner, scope="agent"):         # its own modules (each agent's own working data)
            self.request_wake()
        if await modules.answer(self.state, self.s, self.gm, self.runner, scope="agent"):
            self.request_wake()
        if await happenings.from_modules(self.state, self.s, self.gm, scope="agent"):
            self.request_wake()
        if await stakes.step(self.state, self.s):                          # a stat that ran out, or the agent recovering
            self.request_wake()
        if await self.finish_work():
            self.request_wake()
        if await happenings.step(self.state, self.s, self.gm):
            self.request_wake()
        await wishes.share_step(self.state, self.s, self.outreach)
        await nb.recall_told(self.state, self.gm, self._told_tries)
        if await nb.step(self.state, self.s, self.gm, self.rng, library=self.library):
            self.request_wake()
        if mem.due(self.state, self.s, time.time()):
            await self.reflect()

    async def finish_work(self) -> bool:
        """Resolve whatever the agent was busy with once its time is up: a walk (The agent arrives), or a module's session (work, reading, gathering:
        the module hears it)."""
        async with self._finishing:
            sess = self.state.session()
            if not sess or sess["ends_at"] > time.time():
                return False
            if sess["kind"] == "walk":
                return bool(await places.arrive(self.state, self.s, self.gm, self.library, self.rng))
            if sess["kind"] == "module":
                return bool(await modules.end_session(self.state, self.s, self.ctx.runner))
            self.state.end_session()                  # a kind nothing finishes any more (work, reading, a gather from before): it just ends
            return False

    async def reflect(self) -> dict | None:
        """The agent's nightly reflection (also triggered by POST /reflect). One at a time."""
        with self.acting():
            return await self._reflect()

    async def _reflect(self) -> dict | None:
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
            await self.world.night()                 # then the world's own turn: perhaps one new rule
            return result

    # --- one tick ----------------------------------------------------
    async def tick(self, reason: str) -> None:
        """One wake, as this agent (never while another agent's talk has it)."""
        async with self.talking:
            with self.acting():
                await self._wake_once(reason)

    async def _wake_once(self, reason: str) -> None:
        """One wake. A visitor message the agent read but never answered gets one more look (see _second_chance)."""
        started, self._shown_inbox = time.time(), []
        try:
            await self._tick(reason)
        finally:
            self._second_chance(started)

    def _second_chance(self, started: float) -> None:
        """The agent is told a visitor can only hear it through `say`, but a model busy with its work sometimes forgets.
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
        await stakes.step(self.state, self.s)
        if stakes.out(self.state):                # out cold: nothing until the agent comes to (a visitor's words wait)
            return
        sleepmod.wake_up(self.state)
        await self.finish_work()  # the heartbeat can land right as a session ends: show its result now

        inbox = self.state.pending_inbox()
        if partner := self.world.talking_with(self):                     # in a talk: what they said meanwhile is part of it, not a new one
            mine = [m["id"] for m in inbox if m.get("source") == "agent" and m.get("sender") == partner.identity.name]
            self.state.consume_inbox(mine)
            inbox = [m for m in inbox if m["id"] not in mine]
        if self.s.talk_scenes == "on" and not inbox and self.gm and (ch := talk.waiting(self.state)):
            await self._converse(ch)
            return
        if self.s.talk_scenes == "on" and (other := talk.agent_waiting(self.state, inbox)) and await self._talk_with(other):
            return
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

            await self.outreach.typing([m["id"] for m in inbox])  # "typing..." wherever the agent is about to answer
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
            if inbox and resp.text and not any(c.name == "say" for c in resp.tool_calls):  # a plain-text reply (`say` is the reliable path;
                # beside a `say`, the words are the agent's own closing thoughts, not a second reply)
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
        elif not stakes.allowed(self.state, canonical(call.name)):
            out.update(content="you're too weak for that; eat, rest or sleep until you recover", is_error=True, followup=True)
        elif (mod := await module_tool(self.ctx, call.name, call.arguments, engine_has=bool(entry))) is not None:
            self.state.log("tool", tool=call.name, args=call.arguments, result=mod.text, module=mod.module, **({"first": mod.first} if mod.first else {}),
                           **({"noop": True} if mod.noop else {}))
            out.update(content=mod.text, followup=mod.followup)
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

    def _persona(self) -> str:
        """Who the agent is: the deployment's optional persona file, re-read every time; by default just a name."""
        persona = ""
        if os.path.exists(self.s.persona_path):
            with open(self.s.persona_path) as f:
                persona = f.read().strip()
        return persona or self.pack.persona(self.identity)

    def _system_prompt(self) -> str:
        """The persona followed by how the world works (the guide, built from what is enabled)."""
        return self._persona() + "\n\n" + guide.render(self.tool_names(), self.s, self.library is not None)

    async def _converse(self, ch: dict) -> str:
        """A talk with someone the agent is with in person, as its own scene (see talk.py). Returns how it ended."""
        visit = self.state.meta("arrived_at")
        self.state.set_meta(talk_scene=visit)                        # the monitor leaves this visit's answers to the scene
        turns, ended = 0, "turns"
        try:
            while turns < talk.SCENE_TURNS:
                if self.state.budget_exceeded():
                    ended = "budget"
                    break
                on_mind = reminders.step(self.state, self.s, reminders.cue(self.state, [], time.time(), ch), time.time(), 1)
                resp = await self.backend.complete(system=talk.system(self._persona(), ch),
                                                   messages=[{"role": "user", "content": talk.prompt(self.state, ch, clock_line(time.time()), time.time(), on_mind)}],
                                                   tools=talk.specs(self.tools), max_tokens=self.s.llm_max_tokens)
                self.state.add_usage(resp.usage.input_tokens, resp.usage.output_tokens)
                self.state.log("tick", reason="talk", step=turns, text=resp.text, tokens=resp.usage.input_tokens + resp.usage.output_tokens,
                               tools=[c.name for c in resp.tool_calls])
                turns += 1
                said, bye = False, False
                for i, call in enumerate(resp.tool_calls):
                    if call.name == "say":
                        call.arguments = {**call.arguments, "to": ch["name"]}
                        bye = bye or call.arguments.get("goodbye") is True
                    out = await self._run_tool(call, i)
                    said = said or (call.name == "say" and str(out.get("content", "")).startswith("said it"))
                if not said:
                    ended = "silence"
                    break
                fresh = next((c for c in self.state.characters() if c["id"] == ch["id"]), ch)
                answer = await nb.reply(self.state, self.s, self.gm, fresh, time.time(), self.library, closing=True)
                if bye:
                    ended = "agent"
                    break
                if not answer:
                    ended = "no answer"
                    break
                if answer.get("goodbye") is True:
                    ended = ch["name"]
                    break
        finally:
            self.state.set_meta(talk_scene="", talk_done=visit)
        self.state.log("talk", name=ch["name"], turns=turns, ended=ended)
        self.request_wake()                                              # the world turn takes it from here
        return ended

    async def _talk_with(self, other: "Agent") -> bool:
        """A talk with another agent who is here and spoke to this one (talk.py, "between agents"): started as a task of its own, which
        takes time (`_hold_talk`), so this turn is over at once; its first line takes in what the other said. False if the other couldn't be had (mid-turn): the words are answered in a
        world turn, the old way, as they are when either has spent the day's tokens (no talk: it would end before a word)."""
        if self.state.budget_exceeded() or other.state.budget_exceeded():
            return False
        try:
            await asyncio.wait_for(other.talking.acquire(), talk.LOCK_WAIT)
        except asyncio.TimeoutError:
            return False
        other.talking.release()
        self.world.talks[frozenset((self.identity.key, other.identity.key))] = asyncio.create_task(self._hold_talk(other))
        return True

    async def _hold_talk(self, other: "Agent") -> None:
        """The talk itself: each speaks in turn from its own small prompt, heard at once, a line taking as long as it takes to say and a
        pause (talk.line_seconds), with both free between lines. It ends on a goodbye, a silence, one leaving or falling asleep, one
        running out, or after STRETCH_MINUTES of talk; then each has a world turn."""
        speaker, listener, lines, ended, spoken = self, other, 0, None, 0.0
        first, second = sorted((self, other), key=lambda a: a.identity.key)        # always in one order: two talks can't deadlock
        try:
            while spoken < talk.STRETCH_MINUTES * 60:
                try:
                    await asyncio.wait_for(first.talking.acquire(), talk.LOCK_WAIT)
                except asyncio.TimeoutError:
                    ended = "busy"
                    break
                try:
                    try:
                        await asyncio.wait_for(second.talking.acquire(), talk.LOCK_WAIT)
                    except asyncio.TimeoutError:
                        ended = "busy"
                        break
                    try:
                        ended = talk.cut_short(speaker.state, listener.state)
                        if ended:
                            break
                        with speaker.acting():
                            text, bye = await speaker._scene_line(listener)
                        lines += 1
                        ended = "silence" if not text else speaker.identity.name if bye else None
                        if ended:
                            break
                    finally:
                        second.talking.release()
                finally:
                    first.talking.release()
                speaker, listener = listener, speaker
                spoken += talk.line_seconds(text)
                if spoken < talk.STRETCH_MINUTES * 60:
                    await talk.wait(talk.line_seconds(text))
        finally:
            self.world.talks.pop(frozenset((self.identity.key, other.identity.key)), None)
            now, day = time.time(), time.strftime("%Y-%m-%d")
            for a, b in ((self, other), (other, self)):
                again = a.state.meta(f"company:{b.identity.key}") == day                    # their company already counted today
                a.state.set_meta(**{f"talked:{b.identity.key}": str(now), f"company:{b.identity.key}": day})
                with a.acting():
                    a.state.log("talk", name=b.identity.name, turns=lines, ended=ended or "a while", agent=True, **({"again": True} if again else {}))
                a.request_wake()                                                 # each world turn takes it from here

    async def _scene_line(self, listener: "Agent") -> tuple[str, bool]:
        """This agent's line in a talk with another agent: (what it said, or "" for nothing; whether it said goodbye). Its words are
        heard at once; what the other said to it meanwhile, in a turn of their own, is part of the talk."""
        self.state.consume_inbox([m["id"] for m in self.state.pending_inbox() if m.get("source") == "agent"
                                  and m.get("sender") == listener.identity.name])
        partner = {"name": listener.identity.name, "about": listener.identity.kind}
        on_mind = reminders.step(self.state, self.s, reminders.cue(self.state, [], time.time(), partner), time.time(), 1)
        resp = await self.backend.complete(system=talk.system(self._persona(), partner),
                                           messages=[{"role": "user", "content": talk.prompt(self.state, partner, clock_line(time.time()), time.time(), on_mind)}],
                                           tools=talk.specs(self.tools), max_tokens=self.s.llm_max_tokens)
        self.state.add_usage(resp.usage.input_tokens, resp.usage.output_tokens)
        self.state.log("tick", reason="talk", step=0, text=resp.text, tokens=resp.usage.input_tokens + resp.usage.output_tokens,
                       tools=[c.name for c in resp.tool_calls])
        said, bye = "", False
        for i, call in enumerate(resp.tool_calls):
            if call.name == "say" and not said and str(call.arguments.get("text") or "").strip():
                said = clip(str(call.arguments["text"]).strip(), 600)
                self.state.log("say", text=said, to=[], to_name=listener.identity.name)
                with listener.acting():
                    mid = listener.receive(said, self.identity.name, source="agent", wake=False)
                    listener.state.consume_inbox([mid])
                bye = call.arguments.get("goodbye") is True
            elif call.name != "say":
                await self._run_tool(call, i)
        return said, bye

    def _free_time(self, now: float) -> list[str]:
        """At home with nothing due for a while: say so, with what the agent has said it wants to do. Facts, not orders."""
        if self.state.agent()["location"] != places.HOME or self.state.session() or sleepmod.asleep(self.state):
            return []
        due = [(c["runtime"]["tended_until"] - now) / 60 for c in self.state.creations()
                if "upkeep" in c["spec"]["capabilities"] and cr.running(c, now) and "tended_until" in c["runtime"]]
        standing = modules.standing(self.state)                      # what live modules say waits, or next will
        due += [(x["next_at"] - now) / 60 for x in standing if x.get("next_at", 0) > now]
        if self.state.pending_inbox() or any(x["ready"] for x in standing):
            return []
        free = min(due) if due else None
        if free is not None and free < FREE_MINUTES:
            return []
        lines = [f"Nothing needs you for about {span(round(free))}." if free is not None else "Nothing needs you for now."]
        aims = [m for m in self.state.memories("ambitions", status="open", limit=FREE_SHOWN)]
        wants = [m for m in self.state.memories("wishlist", status="open", limit=20) if m.get("kind") in ("activity", "ability", "idea")][-FREE_SHOWN:]
        if aims:
            lines.append("Your ambitions: " + "; ".join(f"#{m['id']} {clip(m['text'], 100)}" for m in aims))
        if wants:
            lines.append("Things you wish you could do: " + "; ".join(f"#{m['id']} {clip(m['text'], 100)}" for m in wants))
        if "start_project" in self.tool_names() and (aims or wants):
            lines.append("start_project begins something new.")
        if "draw" in self.tools:
            lines.append("draw makes a picture; a small pixel one is quick.")
        return lines

    def _talk(self, inbox: list[dict]) -> list[str]:
        """The conversations the agent is in, in full: a visit under way, and the chat so far with each visitor who is waiting for an answer."""
        now, lines = time.time(), []
        here = places.present_at(self.state)
        agents = [a.identity.name for a in others.here(here)]                         # another agent here: a talk, maybe just had
        for name in [ch["name"] for ch in places.company_at(self.state, here)] + agents:  # whoever is here, of any role
            if said := conv.visit_lines(self.state, name, float(self.state.meta("arrived_at") or 0)):
                lines += [f"Talking with {name} (this visit, oldest first):"] + [f"  {l}" for l in said]
        waiting = {m["id"] for m in inbox}
        for sender in dict.fromkeys(m["sender"] for m in inbox if not m["gift"] and m["sender"] not in agents):
            if said := conv.thread_lines(self.state, sender, now, skip_ids=waiting):
                lines += [f"Your conversation with {sender} so far (oldest first):"] + [f"  {l}" for l in said]
        return lines

    def tool_names(self) -> set[str]:
        """Every tool the agent may have: the engine's it was given, and those live modules offer (trade's `buy`, the garden's `plant`)."""
        return {*self.tools, *(t["name"] for _, t in modules.tools_offered(self.state))}

    def _belongings(self) -> list[str]:
        lines: list[str] = []
        if "use_item" in self.tools:
            items = self.state.items()
            lines.append("Your belongings:")
            lines += [f"- {i['name']} x{i['qty']} ({i['kind']})" + (f": {i['description']}" if i["description"] else "")
                      for i in items] or ["- (nothing)"]
        lines.append(f"Coins: {self.state.coins()}")
        return lines

    def _projects(self) -> list[str]:
        """The things the agent has made (its projects are the crafting module's status)."""
        lines: list[str] = []
        made = self.state.creations()
        if made:
            lines.append("Things you've made:")
            code, mine = modules.bound(self.state), modules.programs(self.state)
            lines += [cr.describe(c) + (f" - actions (use_item with action): {modules.offers_line(code[c['name'].lower()])}"
                                        if c["name"].lower() in code and code[c["name"].lower()]["offers"] else "")
                      + (f" - your program for it: {modules.program_status(mine[c['name'].lower()])}" if c["name"].lower() in mine else "")
                      for c in made]
        return lines

    @staticmethod
    def _moment_text(e: dict) -> str | None:
        """One-line description of an event worth a diary entry, or None for ordinary events."""
        d, k = e["data"], e["kind"]
        if k == "gift":
            return f"{d['sender']} gave you {d['qty']} x {d['item']}"
        if k == "module" and d.get("moment"):               # a moment a module logged (a crop ripening)
            return d["text"]
        if k == "reading" and d.get("finished"):
            return f"You finished reading {d['title']}"
        if k == "arrived" and d.get("first_time") and d["place"] != places.HOME:
            return f"You went to {places.label(d['place'])} for the first time"
        if k == "stakes":
            return stakes.moment(d)
        if k == "creation_made":
            return f"Your {d['project']} became {d['name']}: {d['description']}"
        if (d.get("read") or {}).get("moment"):              # a module's event that says it is a moment of the agent's day
            return d["read"]["moment"]
        if k == "tool":
            t, a, r = d["tool"], d["args"], str(d.get("result", ""))
            if d.get("first") and not r.startswith("error"):   # a module's tool that has a first is a moment each time (planting)
                return r.capitalize()
            if t == "resolve_note" and r.startswith("crossed off"):
                return f"You crossed off #{a.get('id')}" + (f": {a['outcome'][:100]}" if a.get("outcome") else "")
        return None  # visitor messages are summarised separately in _moments

    def _gallery(self) -> list[str]:
        """The last few pictures and pieces, by number, so the agent can send or refer to them."""
        if "draw" not in self.tools and "write_piece" not in self.tools:
            return []
        works = self.state.works(limit=4)
        return (["Your gallery (latest):"] + [f"- #{w['id']} {w['title']} ({'drawing' if w['kind'] == 'drawing' else 'writing'})"
                                              for w in works]) if works else []

    def _calibration(self) -> list[str]:
        """How close the agent's predictions have been, in plain counts (only once there are enough to count)."""
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
        """Notable things since the agent's last diary entry, offered a few times so they aren't forgotten.

        Deterministic about *when* something is worth a diary line; The agent decides what (if anything) to write.
        """
        if "note_to_self" not in self.tools or places.present_at(self.state) != places.home_key():   # the diary is written at home
            return []
        last, now, window = self.state.memories("diary", limit=1), time.time(), self.s.moment_window_minutes * 60
        start, left, back = now - window, float(self.state.meta("left_home_at") or 0), float(self.state.meta("arrived_at") or 0)
        if left and back >= left and now - back < window:                  # just home: what happened on the trip
            start = min(start, left)
        since = max(start, last[0]["ts"] if last else 0)
        moments, visit_ids, visitors, visit_inbox = [], [], [], []
        window = self.state.events_since(since)
        said_to = {i for e in window if e["kind"] == "say" for i in e["data"].get("to", [])}
        for e in window:  # oldest first
            if self._moment_shown.get(e["id"], 0) >= self.s.moment_showings:
                continue
            if e["kind"] == "inbox" and e["data"].get("letter"):
                moments.append(([e["id"]], f"A letter came from {e['data']['sender']}"))
            elif e["kind"] == "inbox":
                visit_ids.append(e["id"])  # never quote visitor text here: The agent would answer it again
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
                where = wishes.doings(self.state, self.s, self.library, m["text"], self.tool_names())
            if where:
                note += f"  [you could try: {'; '.join(where)}]"
            return fmt(m) + note

        visits = [(c["name"], ts) for c in self.state.characters() if c["place"]
                  and (ts := self.state.last_arrived(places.home_of(c)))]                  # going where someone lives

        heard_of = [r for r in invented.records(self.state) if r["status"] == "heard"]

        def fmt_todo(m):
            # a neighbor visited since the to-do was written: the visit may have been the to-do
            since = m["edited_at"] or m["ts"]
            went = [name for name, ts in visits if ts > since and State.related(name, m["text"])]
            note = (f"  [you've since visited {', '.join(went)} - is this done? resolve_note it, or edit_note it down "
                    "to what's left]") if went else ""
            for r in invented.named_in(heard_of, m["text"]):  # somewhere the agent has only heard of: it can go
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
        return lines + calendar.lines(self.state, self.s, self.library)       # commitments with a time: what's coming, what's due

    def _specs(self) -> list:
        """The tools to offer now: what can be done here, described for here. Mid-walk the agent is nowhere yet, so only what works anywhere."""
        if places.present_at(self.state) is None:
            mods = module_specs(self.state, "")
            engine = specs_for(self.tools, "")
        else:
            here = places.here(self.state, self.s, self.library)
            open_ = places.open_now(here, self.s)
            mods = module_specs(self.state, here.key, here, open_)
            engine = specs_for(self.tools, here.key, here, open_)
        names = {t.name for t in mods}                                  # where a module's tool applies, it stands for the engine's of that name
        return [t for t in [t for t in engine if t.name not in names] + mods if stakes.allowed(self.state, t.name)]

    def _perception(self, reason: str, inbox: list[dict]) -> str:
        a = self.state.agent()
        lines = [
            f"Woke because: {reason}",
            f"State: {stats_mod.prompt_line(self.state)}, "
            f"mood {a['mood']}, location {a['location']}, activity {a['activity']}"
            + (f" ({a['description']})" if a["description"] else ""),
            clock_line(time.time()),
        ]
        if "sleep" in self.tools:
            lines += sleepmod.perception(self.state, self.s, time.time())
        lines += stakes.perception(self.state)
        lines += abilities.perception(self.state, time.time())
        lines += emo.perception(self.state, self.s)
        lines += self._firsts()
        lines += self._calibration()
        lines += places.perception(self.state, self.s, self.library)
        lines += mem.perception(self.state)
        lines += reminders.step(self.state, self.s, reminders.cue(self.state, inbox, time.time(), talk.partner(self.state)), time.time(),
                                self.s.reminders_shown)
        lines += np.perception(self.state, self.s)
        lines += self.outreach.perception()
        lines += self._gallery()
        lines += happenings.perception(self.state, self.tools, time.time()) if self.s.happenings != "off" else []
        lines += modules.perception(self.state)
        lines += modules.voices_here(self.state)
        lines += self._free_time(time.time())
        lines += self._belongings()
        lines += modules.status_lines(self.state)
        lines += self._projects()
        lines += nb.perception(self.state)
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
                elif e["kind"] == "module" and d.get("moment"):              # a module's moment: a haul, a crop ripening
                    lines.append(f"- {d['text']}")
                elif e["kind"] == "woke":
                    lines.append(f"- {sleepmod.woke_text(d)}")
                elif e["kind"] == "reading":
                    lines.append(f"- you read {d['title']}" + (f" (now {d['percent']}% through)" if not d["finished"]
                                                                else " (and finished it)") + f": {d['summary']}"
                                 + "".join(f' "{q}"' for q in d.get("quotes", [])))
                elif e["kind"] == "arrived":
                    lines.append(f"- you arrived at {places.label(d['place'])}" if d["place"] != places.HOME
                                 else "- you got home")
                    if d.get("first_time") and d["place"] != places.HOME and "draw" in self.tools:
                        lines[-1] += " for the first time (draw can keep a picture of it)"
                elif e["kind"] == "letter_sent":
                    lines.append(f"- you wrote to {d['to']}: {d['text'][:200]}"
                                 + (f" (enclosed: {d['enclosed']})" if d.get("enclosed") else ""))
                elif e["kind"] == "outreach" and d.get("what") == "postcard" and d.get("delivered"):
                    lines.append(f"- you sent a postcard ({d.get('channel')}): {d['text']}")
                elif e["kind"] == "talk":
                    lines.append(f"- you talked with {d['name']} ({d['turns']} of your lines; "
                                 + ("you said goodbye" if d["ended"] == "agent" else f"{d['name']} said goodbye" if d["ended"] == d["name"]
                                    else "it trailed off") + ")")
                elif e["kind"] in ("module_live", "module_rejected", "module_disabled") and d.get("author") == "agent":
                    lines.append(f"- your program for {d.get('subject') or d['name']} "
                                 + {"module_live": "is working now",
                                    "module_rejected": "wasn't taken up" + (f": {d['note']}" if d.get("note") else ""),
                                    "module_disabled": "was switched off" + (f": {d['why']}" if d.get("why") else "")}[e["kind"]])
                elif e["kind"] == "sold_creation":
                    lines.append(f"- you sold {d['name']} at {places.label(d['place'])} for {coins_text(d['coins'])}")
                elif e["kind"] == "stall_sale":
                    lines.append(f"- at your stall you sold {d['qty']} {d['item']} for {coins_text(d['coins'])}")
                elif e["kind"] == "heard_of_place":
                    lines.append(f"- {d['by']} told you about {places.label(d['place'])}"
                                 + (f": {d['there']}" if d["there"] else ""))
                elif e["kind"] == "companion":  # model-written, so quoted like a visitor's words
                    lines.append(f"- {d['name']} said: \"{d['text']}\"" + (" (answering you)" if d.get("reply") else ""))
                elif e["kind"] == "creation_made":
                    lines.append(f"- you finished making {d['name']} ({d['quality']}): {d['description']}"
                                 + (f" (a drawing of it, with of=\"{d['name']}\", becomes how it looks in your {self.pack.data('places').get('home', {}).get('called', 'home')})" if "draw" in self.tools else ""))
                elif (d.get("read") or {}).get("line") and d.get("by"):     # a module's event, as it says it reads
                    lines.append(f"- {d['read']['line']}")
        def visitor(m):
            if m["gift"]:
                return f"- {m['text']}"
            if m.get("source") == "agent":                       # another agent, here: answered with say(to=...)
                return f"- {m['sender']} (here with you) said: {m['text']} (answer with say(to=\"{m['sender']}\"))"
            if m.get("source") == "letter":                      # another agent's letter, by the world's post
                return f"- a letter from {m['sender']}: {m['text']} (write_letter to answer)"
            via = f" (via {m['source']})" if m.get("source", "web") != "web" else ""
            return f"- {m['sender']}{via}: {m['text']}"
        lines += others.seen(self.state)                         # the other agents here (meeting them, the first time)
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
