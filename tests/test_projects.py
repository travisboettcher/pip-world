import random


from app import tools as tools_mod
from app.config import Settings
from app.llm.base import LLMResponse, ToolCall, Usage
from app.llm.fake import FakeBackend
from app.loop import Agent
from app.pacing import get_policy
from app.state import State

PLAN = {"craft": "Clockmaking", "difficulty": 3, "tools": ["needle file", "tweezers"], "stages": [
    {"name": "cut the wheels", "minutes": 60, "materials": {"brass wire": 2}},
    {"name": "fit the escapement", "minutes": 30},
]}


def report(**args):
    return LLMResponse("", [ToolCall("r", "report", args)], Usage(10, 5))


class FixedRng(random.Random):
    def __init__(self, *values):
        super().__init__(0)
        self.values = list(values)

    def random(self):
        return self.values.pop(0) if self.values else 0.5


def make(tmp_path, gm_script=None, rng=None, **kw):
    kw.setdefault("reflect_hour", 99)  # no nightly reflection unless a test asks for one
    kw.setdefault("neighbor", False)    # no neighbor unless a test asks for one
    kw.setdefault("sleep", False)       # no day/night rhythm unless a test asks for one
    kw.setdefault("night_pass", "off")  # no night pass unless a test asks for one
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/nonexistent",
                 tools=["set_activity", "eat", "rest", "note_to_self", "use_item", "sleep"], min_tick_interval=0, **kw)
    st = State(s)
    gm = FakeBackend(gm_script)
    agent = Agent(s, st, FakeBackend(), get_policy(s), gm_backend=gm, rng=rng or FixedRng())
    return s, st, gm, agent


PIP_STEPS = [{"name": st["name"], "minutes": st["minutes"], "materials": st.get("materials", {})}
             for st in PLAN["stages"]]


THREE_STEPS = [{"name": "gather and shape the pieces", "minutes": 45}, {"name": "put it together", "minutes": 60},
               {"name": "finish and test", "minutes": 45}]


CRAFTING_TOOLS = ("start_project", "work_on", "experiment", "revise_plan", "abandon_project", "resume_project")


def crafting(st, **params):
    """The shipped crafting module, live (it is the agent's projects since 0.42.0)."""
    from app import modules as M
    from tests.test_modules import live
    if M.live_named(st, "crafting"):
        return M.live_named(st, "crafting")
    man, src = M.library("crafting")
    man.pop("reason", None)
    return live(st, {**man, "params": {**man["params"], "speed": st.s.work_speed, "most": st.s.max_active_projects,
                                        "cap": st.s.max_active_projects_cap, **params}}, src, author=M.SHIPPED)


async def given(st, *projects, skills=None, extra_slots=0):
    """Projects (and crafts' experience) as the crafting module keeps them, published as it publishes them. Each project names what the
    test cares about (its stages' name, minutes and progress at least); the rest is a plain new project's."""
    import time
    from app import modules as M
    m = crafting(st)
    ps = {}
    for i, p in enumerate(projects, start=1):
        stages = [{"guess": s.get("minutes", 60), "materials": {}, "abilities": ["handiness"], "progress": 0.0, "started": False, **s}
                  for s in p.get("stages", [])]
        full = {"id": i, "goal": "", "craft": "clockmaking", "difficulty": 2, "tools": [], "questions": [], "hidden": [], "findings": [],
                "history": [], "status": "active", "dry": 0, "revised_at": 0, "ts": time.time(), "finished_at": None, "outcome": "",
                **p, "stages": stages}
        ps[str(full["id"])] = full
    st.merge_store("crafting", {"projects": ps, "skills": skills or {}, "meta": {"all": {"next_id": len(ps) + 1, "extra_slots": extra_slots}}})
    await M.call(st, st.s, M.LocalRunner(), m, "on_install", time.time())
    return M.live_named(st, "crafting")


async def _module_tool(agent, tool, args):
    out = await agent._run_tool(ToolCall(id="1", name=tool, arguments=args), 0)
    return tools_mod.ToolResult(out["content"], followup=bool(out.get("followup")))


def call(agent, tool, **args):
    """A tool, as the agent uses it: the engine's own, or (crafting's) the module's, made live first."""
    if tool == "start_project":  # the plan is Pip's: default steps unless a test supplies its own
        args.setdefault("steps", PIP_STEPS if "clock" in args["name"].lower() else THREE_STEPS)
    if tool in CRAFTING_TOOLS:
        crafting(agent.state)
        return _module_tool(agent, tool, args)
    return tools_mod.REGISTRY[tool][1](agent.ctx, args)
