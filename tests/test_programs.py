"""Modules, step 3 (docs/DESIGN-modules.md, "Pip's creations as code"): Pip programs its creations; and the owner hears of anything waiting."""
import time

import pytest

from app import creations as cr
from app import modules as M
from app import tools as T
from app.channels import FakeChannel
from app.outreach import Outreach
from tests.test_modules import NOW, live, modular, rule
from tests.test_projects import call
from tests.test_world_view import TIMEKEEPER, clock

BELL = ('def on_install(ctx):\n    return {"offer": [{"name": "ring", "help": "ring it"}]}\n'
        'def on_action(ctx):\n    return {"reply": "ding", "state": {"rung": ctx["state"].get("rung", 0) + 1}}\n')


def programmer(tmp_path, **kw):
    s, st, agent = modular(tmp_path, **kw)
    agent.tools["program"] = T.REGISTRY["program"]
    return s, st, agent


def thing(st, name="Brass Bell", quality="sound", caps=None):
    return st.add_creation(name, "a bell", None, quality, {"capabilities": caps or {}, "quirks": []}, {})


# --- the manifest Pip never has to write -------------------------------------------------------------------------------------
def test_a_programs_manifest_comes_from_its_code(tmp_path):
    s, st, agent = programmer(tmp_path)
    bell = thing(st)
    man = M.program_manifest(BELL, bell)
    assert man == {"name": "brass-bell-by-pip", "kind": "thing", "api": 1, "subject": "Brass Bell", "hooks": ["on_install", "on_action"],
                   "reads": list(M.PIP_READS), "proposes": list(M.PIP_PROPOSES), "events": [], "consumes": {"*": 2}}
    assert M.check_manifest(man, "pip", st)["name"] == "brass-bell-by-pip"
    c = clock(st)
    man = M.program_manifest("def on_event(ctx):\n    pass\ndef helper():\n    pass\n", c, ["garden", 5])
    assert man["tends"] == "tend" and man["hooks"] == ["on_event"] and man["events"] == ["garden"]
    with pytest.raises(M.Refused) as e:
        M.program_manifest("def helper(ctx):\n    pass\n", bell)
    assert str(e.value) == "define at least one of on_install, on_tick, on_time, on_event, on_action"
    with pytest.raises(M.Refused) as e:
        M.program_manifest("def on_event(ctx):\n    pass\n", bell)
    assert str(e.value) == "on_event needs `events`: the kinds of thing that happen it listens for"
    with pytest.raises(M.Refused) as e:
        M.program_manifest(BELL, bell, ["garden"])
    assert str(e.value) == "`events` is only for a program with on_event"
    with pytest.raises(M.sandbox.Rejected):
        M.program_manifest("import os", bell)


def test_pips_programs_are_held_to_less_than_the_worlds(tmp_path):
    s, st, agent = programmer(tmp_path)
    thing(st)
    with pytest.raises(M.Refused) as e:
        M.check_manifest(rule(), "pip", st)
    assert str(e.value) == "your programs make one of your creations work"
    with pytest.raises(M.Refused) as e:
        M.check_manifest(rule(kind="thing", subject="Brass Bell", reads=["works", "time"], proposes=["publish"]), "pip", st)
    assert str(e.value) == "your programs can't use: works, publish"
    m = live(st, rule(kind="thing", subject="Brass Bell", proposes=["show"]), "x", author="pip")
    pic = {"rows": ["kkkk"] * 4, "palette": {"k": "#000"}}
    with pytest.raises(M.Refused) as e:
        M.plan(st, m, {"show": [{"id": "a", "sprite": pic, "at": {"type": "floor", "place": "home"}}]}, NOW, "on_tick")
    assert str(e.value) == 'your things show themselves where they are: `at.place` is "subject"'
    assert M.plan(st, m, {"show": [{"id": "a", "sprite": pic, "at": {"type": "floor", "place": "subject"}}]}, NOW, "on_tick")


# --- writing one -----------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pip_writes_a_program_sees_its_trial_and_it_waits_to_be_tried(tmp_path):
    s, st, agent = programmer(tmp_path)
    thing(st)
    r = await call(agent, "program", creation="brass bell", code=BELL)
    m = M.programs(st)["brass bell"]
    assert r.text == ("you write a program for your Brass Bell (version 1). On a trial run it was called 2 times. Using it: ring: ding. "
                      "It offers: ring. It waits to be tried; you'll hear when it's working.") and r.followup
    assert (m["author"], m["status"], m["reason"], m["subject"]) == ("pip", "waiting", "Pip's program for its Brass Bell.", "Brass Bell")
    assert st.events(1)[0]["kind"] == "programmed" and st.events(1)[0]["data"] == {"name": "Brass Bell", "version": 1, "status": "waiting"}
    assert "- Brass Bell (sound): a bell - your program for it: version 1 waiting to be tried" in agent._projects()
    r = await call(agent, "program", creation="Brass Bell", code=BELL.replace("ding", "dong"))
    assert "(version 2)" in r.text and st.module(m["id"])["status"] == "replaced"                     # the newer one supersedes it
    two = M.programs(st)["brass bell"]
    await M.approve(st, s, agent.runner, two["id"])
    assert "- your program for Brass Bell is working now" in agent._perception("timer", [])
    assert "your program for it: working (version 2)" in "\n".join(agent._projects())
    st.db.execute("UPDATE creations SET quality = 'masterwork'")                                    # no misfire to spoil it
    st.db.commit()
    assert (await call(agent, "use_item", item="brass bell", purpose="hear it", action="ring")).text == "dong"


@pytest.mark.asyncio
async def test_what_goes_wrong_is_said_plainly(tmp_path):
    s, st, agent = programmer(tmp_path)
    thing(st)
    assert (await call(agent, "program", creation="moon lamp", code=BELL)).text == "you have no creation called 'moon lamp'"
    r = await call(agent, "program", creation="brass bell", code="import os")
    assert r.text.startswith("your program wasn't accepted: line 1: `import os` isn't allowed") and r.text.endswith("Fix it and send it again.")
    r = await call(agent, "program", creation="brass bell", code="def on_action(ctx):\n    return 1/0\n")
    assert "It went wrong:" not in r.text and "It offers" not in r.text                                    # no offers: nothing to try
    r = await call(agent, "program", creation="brass bell", code="def on_install(ctx):\n    return {'perceive': 5}\n")
    assert "Not allowed: on_install: `perceive` is a line of text." in r.text and r.text.endswith("You could fix what went wrong and send it again.")
    r = await call(agent, "program", creation="brass bell", code="def on_tick(ctx):\n    return 1/0\n")
    assert "It went wrong: on_tick: line 2: ZeroDivisionError: division by zero." in r.text
    agent.ctx.runner = None
    assert (await call(agent, "program", creation="brass bell", code=BELL)).text == "you can't try programs right now"


@pytest.mark.asyncio
async def test_a_day_holds_only_so_many_programs(tmp_path):
    s, st, agent = programmer(tmp_path)
    thing(st)
    for _ in range(M.PROGRAMS_PER_DAY):
        assert "you write a program" in (await call(agent, "program", creation="brass bell", code=BELL)).text
    assert (await call(agent, "program", creation="brass bell", code=BELL)).text == f"you've written {M.PROGRAMS_PER_DAY} programs today; that's enough for one day"
    st.set_meta(programs_day="2000-01-01")
    assert "you write a program" in (await call(agent, "program", creation="brass bell", code=BELL)).text


def test_the_program_tool_needs_modules(tmp_path):
    from app.config import Settings
    assert "program" in T.enabled_tools(Settings(modules="on", tools=["program"]))
    assert "program" not in T.enabled_tools(Settings(modules="off", tools=["program"]))


@pytest.mark.asyncio
async def test_rejected_and_switched_off_programs_are_heard_of(tmp_path):
    s, st, agent = programmer(tmp_path)
    thing(st)
    await call(agent, "program", creation="brass bell", code=BELL)
    m = M.programs(st)["brass bell"]
    M.reject(st, m["id"], "it rings too much")
    assert "- your program for Brass Bell wasn't taken up: it rings too much" in agent._perception("timer", [])
    assert "your program for it: version 1 not taken up: it rings too much" in "\n".join(agent._projects())
    r = await call(agent, "program", creation="brass bell", code=BELL)
    assert "(version 1)" in r.text                                                                       # a rejected one isn't built on
    m = M.programs(st)["brass bell"]
    await M.approve(st, s, agent.runner, m["id"])
    M.disable(st, m["id"], "too loud")
    assert "- your program for Brass Bell was switched off: too loud" in agent._perception("timer", [])
    assert M.program_status(st.module(m["id"])) == "switched off: too loud"
    assert M.program_status({**m, "status": "disabled", "note": ""}) == "switched off" and M.program_status({**m, "status": "odd"}) == "odd"


# --- one module runs a thing; tending; craft --------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pips_program_takes_over_from_the_worlds_and_tend_uses_its_tend(tmp_path):
    s, st, agent = programmer(tmp_path)
    agent.tools["tend"] = T.REGISTRY["tend"]
    clock(st)
    st.db.execute("UPDATE creations SET quality = 'masterwork'")                                    # no misfires in this test
    st.db.commit()
    world_one = [i for i in await M.offer_library(st, s, agent.runner, now=NOW) if st.module(i)["subject"]][0]
    await M.approve(st, s, agent.runner, world_one, now=NOW)
    no_tend = 'def on_install(ctx):\n    return {"offer": [{"name": "polish", "help": "shine it"}]}\n'
    await call(agent, "program", creation="gear clock", code=no_tend)
    await M.approve(st, s, agent.runner, M.programs(st)["gear clock"]["id"])
    assert st.module(world_one)["status"] == "replaced" and [m["author"] for m in st.modules("live") if m["kind"] == "thing"] == ["pip"]
    assert (await call(agent, "tend", creation="gear clock")).text.startswith("you tend your Gear Clock (wound)")      # its program doesn't tend: built in
    tends = 'def on_install(ctx):\n    return {"offer": [{"name": "tend", "help": "wind it"}]}\ndef on_action(ctx):\n    return {"reply": "you wind it your way"}\n'
    await call(agent, "program", creation="gear clock", code=tends)
    await M.approve(st, s, agent.runner, M.programs(st)["gear clock"]["id"])
    assert (await call(agent, "tend", creation="gear clock")).text == "you wind it your way"


@pytest.mark.asyncio
async def test_rough_work_sometimes_doesnt_respond_and_the_worlds_never_misfires(tmp_path):
    s, st, agent = programmer(tmp_path)
    rough, master = thing(st, "Rough Bell", "rough"), thing(st, "Fine Bell", "masterwork")
    a = live(st, rule(kind="thing", name="rough-bell", subject="Rough Bell", hooks=["on_action", "on_install"]), BELL, author="pip")
    b = live(st, rule(kind="thing", name="fine-bell", subject="Fine Bell", hooks=["on_action"]), BELL, author="pip")
    w = live(st, rule(kind="thing", name="world-bell", subject="Rough Bell", hooks=["on_action"]), BELL)
    times = range(int(NOW), int(NOW) + 400)
    rough_misses = [t for t in times if M.misfires(st, a, "on_action", t)]
    assert 0.15 < len(rough_misses) / 400 < 0.35 and not any(M.misfires(st, b, "on_action", t) for t in times)
    assert not any(M.misfires(st, w, "on_action", t) for t in times) and not any(M.misfires(st, a, "on_install", t) for t in times)
    assert M.misfires(st, a, "on_action", rough_misses[0]) is True                                         # the same moment, the same luck
    st.update_module(a["id"], offers=[{"name": "ring", "help": "x"}])
    got = await M.act(st, s, agent.runner, st.module(a["id"]), "ring", {}, now=rough_misses[0])
    assert got == "it doesn't respond this time (it's rough work; try again)"
    assert st.module_calls(a["id"])[0]["summary"] == "misfired (the work is rough)"
    hit = next(t for t in times if t not in rough_misses)
    assert await M.act(st, s, agent.runner, st.module(a["id"]), "ring", {}, now=hit) == "ding"
    st.give_creation(rough["id"], "Oriel")
    assert not M.misfires(st, a, "on_action", rough_misses[0])                                            # nothing there to misfire


@pytest.mark.asyncio
async def test_the_trial_text_covers_everything_it_saw():
    rep = {"calls": 3, "errors": ["e1", "e1", "e2", "e3", "e4"], "refused": ["r"], "perceived": ["p"], "logged": ["l"], "replies": ["x: y"],
           "unplaced": ["u"], "offers": ["ring", "set"], "placed": ["a: floor at workshop"]}
    assert M.trial_text(rep) == ("On a trial run it was called 3 times. It went wrong: e1; e2; e3. Not allowed: r. It would tell you: p. "
                                 "It would note: l. Using it: x: y. Couldn't show: u. It offers: ring, set. It shows itself: a: floor at workshop.")
    assert M.trial_text({"skipped": "no runner"}) == "It couldn't be tried just now."
    assert M.trial_text({"calls": 0}) == "On a trial run it was called 0 times."


# --- telling the owner -------------------------------------------------------------------------------------------------------
async def told(tmp_path, **kw):
    kw.setdefault("modules_notify", "on")
    s, st, agent = programmer(tmp_path, **kw)
    ch = FakeChannel()
    agent.outreach = Outreach(s, st, [ch], receive=agent.receive)
    return s, st, agent, ch


@pytest.mark.asyncio
async def test_the_owner_hears_once_of_a_module_waiting_and_of_one_switched_off(tmp_path):
    s, st, agent, ch = await told(tmp_path, dashboard_url="https://pip.example/")
    thing(st)
    await call(agent, "program", creation="brass bell", code=BELL)
    m = M.programs(st)["brass bell"]
    assert await M.notify_owner(st, s, agent.outreach) == 1
    assert ch.notices == [(f"pip-world: a module is waiting for your approval - brass-bell-by-pip v1 by Pip, for Brass Bell. "
                           f"Pip's program for its Brass Bell. Trial run: 2 calls, clean. https://pip.example/ui/#work (pipchat modules show {m['id']})", None)]
    assert await M.notify_owner(st, s, agent.outreach) == 0 and st.module(m["id"])["notified"] == "waiting"
    await M.approve(st, s, agent.runner, m["id"])
    M.disable(st, m["id"], "its code failed 3 times in a row: boom")
    assert await M.notify_owner(st, s, agent.outreach) == 1
    assert ch.notices[-1][0] == f"pip-world: module brass-bell-by-pip v1 by Pip, for Brass Bell was switched off: its code failed 3 times in a row: boom https://pip.example/ui/#work (pipchat modules show {m['id']})"
    await M.approve(st, s, agent.runner, m["id"])
    M.disable(st, m["id"], "switched off by the owner")
    assert await M.notify_owner(st, s, agent.outreach) == 0                                       # the owner knows: they did it


@pytest.mark.asyncio
async def test_a_world_module_notice_and_one_without_a_trial_or_link(tmp_path):
    s, st, agent, ch = await told(tmp_path, modules_notify_room="!alerts:test")
    r = await M.propose(st, s, None, "world", rule(name="bells"), "def on_tick(ctx):\n    return {}\n", "for the hours")
    await M.notify_owner(st, s, agent.outreach)
    assert ch.notices == [(f"pip-world: a module is waiting for your approval - bells v1 by the world. for the hours (pipchat modules show {r['id']})", "!alerts:test")]
    bad = await M.propose(st, s, agent.runner, "world", rule(name="broken"), "def on_tick(ctx):\n    return 1/0\n")
    await M.notify_owner(st, s, agent.outreach)
    assert ch.notices[-1][0].endswith(f"Trial run: {M.FAILS_TO_DISABLE} calls, with problems. (pipchat modules show {bad['id']})")


@pytest.mark.asyncio
async def test_no_notices_when_off_or_no_channel_and_a_failed_one_is_tried_again(tmp_path):
    s, st, agent, ch = await told(tmp_path, modules_notify="off")
    await M.propose(st, s, None, "world", rule(name="bells"), "def on_tick(ctx):\n    return {}\n")
    assert await M.notify_owner(st, s, agent.outreach) == 0 and ch.notices == []
    s.modules_notify = "on"
    assert await M.notify_owner(st, s, None) == 0
    ch.fail = True
    assert await M.notify_owner(st, s, agent.outreach) == 0 and st.modules()[0]["notified"] == ""
    assert st.events(1)[0]["kind"] == "owner_notice" and st.events(1)[0]["data"]["status"] == "failed" and st.events(1)[0]["data"]["error"]
    ch.fail = False
    assert await M.notify_owner(st, s, agent.outreach) == 1 and st.events(1)[0]["data"]["status"] == "sent"
    assert await Outreach(s, st, []).notify_owner("x") is False
    s.outreach = "off"
    assert await Outreach(s, st, [ch]).notify_owner("x") is False
    s.outreach = "log"
    assert await Outreach(s, st, [ch]).notify_owner("logged only") is True and st.events(1)[0]["data"] == {"channel": "fake", "text": "logged only", "status": "logged"}


@pytest.mark.asyncio
async def test_the_loop_tells_the_owner(tmp_path):
    s, st, agent, ch = await told(tmp_path)
    await M.propose(st, s, None, "world", rule(name="bells"), "def on_tick(ctx):\n    return {}\n")
    await agent.resolve_world()
    assert [t.split(" - ")[1].split(" v1")[0] for t, _ in ch.notices] == ["bells"]          # the shipped ones went live: nothing to tell
    assert {m["name"] for m in st.modules("live")} >= set(M.RULES)


@pytest.mark.asyncio
async def test_matrix_sends_a_notice_to_pips_room_or_another(tmp_path):
    from tests.test_matrix_channel import ROOM, MatrixHarness
    from tests.test_projects import make
    s, st, *_ = make(tmp_path)
    hx = MatrixHarness(st)
    res = await hx.channel.notice("a module waits")
    assert res.delivered and hx.server.sent[-1]["body"] == {"msgtype": "m.notice", "body": "a module waits"}
    assert f"/rooms/{ROOM}/send/m.room.message/" in hx.server.requests[-1][1]
    await hx.channel.notice("elsewhere", "!alerts:test")
    assert "/rooms/!alerts:test/send/" in hx.server.requests[-1][1]
    hx.server.fail_sends = True
    bad = await hx.channel.notice("x")
    assert not bad.delivered and bad.error
    from app.matrix import MatrixChannel
    from app.config import Settings
    unconfigured = MatrixChannel(Settings(), None)
    assert (await unconfigured.notice("x")).error == "the Matrix channel is not configured"


@pytest.mark.asyncio
async def test_a_trial_never_misfires_even_for_rough_work(tmp_path):
    s, st, agent = programmer(tmp_path)
    thing(st, "Rough Bell", "rough")
    src = 'def on_tick(ctx):\n    return {"state": {"n": ctx["state"].get("n", 0) + 1}, "log": "tick"}\n'
    r = await M.propose(st, s, agent.runner, "pip", M.program_manifest(src, st.creations()[0]), src, now=NOW)
    calls = M.DRY_HOURS * 60 // M.DRY_STEP_MINUTES
    assert r["report"]["calls"] == calls and M.PER_DAY["log"] <= len(r["report"]["logged"]) <= calls and not r["report"]["errors"]
    assert len(r["report"]["logged"]) + len(r["report"]["refused"]) == calls                     # every call ran: none misfired


@pytest.mark.asyncio
async def test_notices_word_for_word_when_things_go_wrong(tmp_path):
    from app.channels import SendResult
    s, st, agent = programmer(tmp_path)
    ch = FakeChannel()
    out = Outreach(s, st, [ch])

    async def boom(text, room=None):
        raise RuntimeError("homeserver gone")
    ch.notice = boom
    assert await out.notify_owner("hello") is False
    e = st.events(1)[0]
    assert e["kind"] == "owner_notice" and e["data"] == {"channel": "fake", "text": "hello", "status": "failed", "error": "RuntimeError: homeserver gone"}

    async def ok(text, room=None):
        return SendResult(True)
    ch.notice = ok
    assert await out.notify_owner("again") is True
    e = st.events(1)[0]
    assert e["kind"] == "owner_notice" and e["data"] == {"channel": "fake", "text": "again", "status": "sent"}
    s.outreach = "log"
    await out.notify_owner("logged")
    assert st.events(1)[0]["kind"] == "owner_notice"


@pytest.mark.asyncio
async def test_matrix_notice_results_exactly(tmp_path):
    import httpx
    from app.channels import SendResult
    from tests.test_matrix_channel import MatrixHarness
    from tests.test_projects import make
    s, st, *_ = make(tmp_path)
    hx = MatrixHarness(st)
    assert await hx.channel.notice("fine") == SendResult(True)
    hx.server.fail_sends = True
    bad = await hx.channel.notice("x")
    assert bad.delivered is False and "500" in bad.error

    async def broken(*a, **k):
        raise ValueError("no route")
    hx.channel._put_event = broken
    assert await hx.channel.notice("x") == SendResult(False, error="ValueError: no route")
    from app.config import Settings
    from app.matrix import MatrixChannel
    assert await MatrixChannel(Settings(), None).notice("x") == SendResult(False, error="the Matrix channel is not configured")


def test_owner_notices_skip_whats_settled_and_word_a_bare_module(tmp_path):
    s, st, agent = programmer(tmp_path, dashboard_url="https://pip.example")
    m = live(st, rule(name="bells"), "x")
    assert M.owner_notices(st, s) == []                                                      # live: nothing to decide
    st.update_module(m["id"], status="waiting")
    assert M.owner_notices(st, s) == [(m["id"], "waiting", f"pip-world: a module is waiting for your approval - bells v1 by the world. "
                                                             f"https://pip.example/ui/#work (pipchat modules show {m['id']})")]


def test_programs_status_words_and_whose_programs_count(tmp_path):
    s, st, agent = programmer(tmp_path)
    thing(st)
    live(st, rule(kind="thing", name="world-bell", subject="Brass Bell"), "x")
    assert M.programs(st) == {}
    p = live(st, rule(kind="thing", name="brass-bell-by-pip", subject="Brass Bell"), "x", author="pip")
    assert list(M.programs(st)) == ["brass bell"]
    assert M.program_status({**p, "status": "proposed"}) == "version 1 waiting to be tried"
    assert M.program_status({**p, "status": "rejected", "note": ""}) == "version 1 not taken up"
    thing(st, "Odd Bell", "peculiar")
    q = live(st, rule(kind="thing", name="odd-bell", subject="Odd Bell"), "x", author="pip")
    assert not any(M.misfires(st, q, "on_action", t) for t in range(int(NOW), int(NOW) + 200))         # an unknown quality never misfires
