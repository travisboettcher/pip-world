import asyncio
import logging
import os
import time

from .config import Settings
from .llm.base import LLMBackend, assistant_message
from .pacing import PacingPolicy
from .state import State
from .tools import ToolContext, enabled_tools

log = logging.getLogger("agent")
MAX_TOOL_CALLS = 4
EVENT_CONTEXT = 15
DIARY_SHOWN = 5
LIST_SHOWN = 10
LEARNED_SHOWN = 5
DIARY_NUDGE_SECONDS = 1800
HIDDEN_EVENT_KINDS = {"alert", "tick_start"}


class Agent:
    def __init__(self, settings: Settings, state: State, backend: LLMBackend, pacing: PacingPolicy):
        self.s, self.state, self.backend, self.pacing = settings, state, backend, pacing
        self.tools = enabled_tools(settings)
        self.ctx = ToolContext(state, settings)
        self.last_tick = 0.0
        self._wake = asyncio.Event()
        self._force = False
        self._budget_logged = False
        self.ticks = 0

    # --- wake control ------------------------------------------------
    def request_wake(self, force: bool = False) -> None:
        self._force = self._force or force
        self._wake.set()

    async def _sleep(self) -> str:
        """Block until the policy says it's time. Returns the wake reason."""
        while True:
            delay = self.pacing.next_delay(time.time(), self.last_tick)
            if self._wake.is_set():
                self._wake.clear()
                if self._force:
                    self._force = False
                    return "forced"
                if self.pacing.wakes_on_events:
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

    async def _monitor(self) -> None:
        """Cheap, LLM-free: advance stats and wake the agent when a threshold is crossed."""
        while True:
            await asyncio.sleep(self.s.monitor_seconds)
            for alert in self.state.apply_decay():
                self.state.log("alert", stat=alert)
                self.request_wake()

    # --- one tick ----------------------------------------------------
    async def tick(self, reason: str) -> None:
        """One wake: up to max_calls_per_tick LLM calls.

        The first call always happens; further calls happen only when a tool result
        asks for a follow-up (ToolResult.followup), so the model can use fresh
        information immediately. Anything still pending when the call cap or the
        daily budget is hit is left for the next tick (and an early wake is requested).
        """
        self.last_tick = time.time()
        self.state.apply_decay()

        inbox = self.state.pending_inbox()
        self.ctx.visitor_ids = [m["id"] for m in inbox]
        messages: list[dict] = [{"role": "user", "content": self._perception(reason, inbox)}]
        specs = [spec for spec, _ in self.tools.values()]

        for step in range(max(1, self.s.max_calls_per_tick)):
            if self.state.budget_exceeded():
                if not self._budget_logged:
                    self.state.log("budget_exceeded", **self.state.usage_today())
                    self._budget_logged = True
                if step:
                    self.request_wake()  # follow-up is waiting on budget
                return
            self._budget_logged = False

            resp = await self.backend.complete(
                system=self._persona(), messages=messages, tools=specs,
                max_tokens=self.s.llm_max_tokens,
            )
            self.state.add_usage(resp.usage.input_tokens, resp.usage.output_tokens)
            if step == 0:
                self.state.consume_inbox([m["id"] for m in inbox])
                if inbox:
                    self.state.log("inbox_read", ids=[m["id"] for m in inbox])
                self.ticks += 1
            self.state.log("tick", reason=reason, step=step, text=resp.text,
                           tokens=resp.usage.input_tokens + resp.usage.output_tokens,
                           tools=[c.name for c in resp.tool_calls])
            if inbox and resp.text:  # plain-text reply (the `say` tool is the reliable path)
                self.state.log("say", text=resp.text, to=[m["id"] for m in inbox])
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
        entry = self.tools.get(call.name)
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
                self.state.log("tool", tool=call.name, args=call.arguments, result=result.text)
                out.update(content=result.text, followup=result.followup)
        return out

    def _persona(self) -> str:
        for p in (self.s.persona_path, self.s.persona_default_path):
            if os.path.exists(p):
                return open(p).read()
        return "You are a small autonomous creature living in a room."

    def _journal(self) -> list[str]:
        def fmt(m): return f"- #{m['id']} {m['text'][:200]}"
        lines: list[str] = []
        diary = self.state.memories("diary", limit=DIARY_SHOWN)
        lines += ["Your diary (latest entries):"] + [fmt(m) for m in diary] if diary else ["Your diary is empty."]
        for section, label, hint in (
            ("todo", "Your to-do list (open)", "nothing planned - anything you'd like to get done?"),
            ("wishlist", "Your wishlist (open)", "nothing yet - what do you want?"),
            ("ambitions", "Your ambitions (open)", "none yet - what would you like to achieve?"),
        ):
            items = self.state.memories(section, status="open", limit=LIST_SHOWN)
            lines += [f"{label}:"] + ([fmt(m) for m in items] if items else [f"- ({hint})"])
        learned = self.state.memories("learned", limit=LEARNED_SHOWN)
        if learned:
            lines += ["Things you've learned:"] + [fmt(m) for m in learned]
        if diary:
            quiet = time.time() - diary[-1]["ts"]
            if quiet > DIARY_NUDGE_SECONDS:
                lines.append(f"(You haven't written in your diary for {int(quiet // 60)} minutes.)")
        return lines

    def _perception(self, reason: str, inbox: list[dict]) -> str:
        a = self.state.agent()
        lines = [
            f"Woke because: {reason}",
            f"State: hunger {a['hunger']:.2f} (1=starving), energy {a['energy']:.2f} (0=exhausted), "
            f"mood {a['mood']}, location {a['location']}, activity {a['activity']}"
            + (f" ({a['description']})" if a["description"] else ""),
        ]
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
                    lines.append(f"- you used {d['tool']}({d['args']}) -> {d['result']}")
        if inbox:
            lines.append("Inbox (visitors):")
            lines += [f"- {m['text']}" for m in inbox]
        return "\n".join(lines)
