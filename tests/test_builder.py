"""Modules, step 4 (docs/DESIGN-modules.md, "The builder"): once a night, the world may propose one small rule of its own."""
import time
from datetime import datetime

import pytest

from app import builder as B
from app import modules as M
from tests.test_modules import NOW, live, rule
from tests.test_projects import make, report

BELL = ('def on_install(ctx):\n    return {"schedule": ctx["now"] + 3600}\n'
        'def on_time(ctx):\n    return {"log": "The bell in the square rings.", "schedule": ctx["now"] + 3600}\n')
BROKEN = 'def on_tick(ctx):\n    return 1/0\n'


def world(tmp_path, script=(), **kw):
    for k, v in (("modules", "on"), ("module_runner", "local"), ("module_builder", "on")):
        kw.setdefault(k, v)
    s, st, gm, agent = make(tmp_path, list(script), **kw)
    return s, st, gm, agent


def draft(**kw):
    return report(**{"action": "propose", "name": "Market Bell", "reason": "A bell for the hours.", "code": BELL, **kw})


FITS = report(fits=True, why="Quiet, and new.")


async def night(st, s, agent, now=NOW):
    return await B.night(st, s, agent.gm, agent.runner, now)


# --- when it runs ------------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_builder_runs_once_a_night_and_only_when_it_can(tmp_path):
    s, st, gm, agent = world(tmp_path, [report(action="nothing", reason="The world is fine as it is.")])
    assert await B.night(st, s, None, agent.runner, NOW) is None and await B.night(st, s, agent.gm, None, NOW) is None
    s.module_builder = "off"
    assert await night(st, s, agent) is None
    s.module_builder = "on"
    assert await night(st, s, agent) == {"outcome": "nothing", "why": "The world is fine as it is."}
    assert st.events(1)[0]["kind"] == "builder" and st.events(1)[0]["data"] == {"outcome": "nothing", "why": "The world is fine as it is."}
    assert await night(st, s, agent, NOW + 60) is None and len(gm.calls) == 1                     # once a night
    assert st.meta("builder_day") == datetime.fromtimestamp(NOW).date().isoformat()
    assert (await night(st, s, agent, NOW + 86400)) == {"outcome": "failed", "why": "the GM gave no answer"}   # the next night it tries again


@pytest.mark.asyncio
async def test_a_proposal_that_fits_waits_for_the_owner(tmp_path):
    s, st, gm, agent = world(tmp_path, [draft(name="Market Bell!!"), FITS])
    r = await night(st, s, agent)
    m = st.module(r["module"])
    assert r == {"outcome": "proposed", "name": "market-bell", "module": m["id"], "status": "waiting", "clean": True, "revised": False}
    assert (m["author"], m["kind"], m["reason"], m["source"]) == ("world", "rule", "A bell for the hours.", BELL)
    assert m["manifest"]["hooks"] == ["on_install", "on_time"] and m["manifest"]["proposes"] == list(B.RULE_PROPOSES)
    assert m["manifest"]["reads"] == [r for r in M.READS if r != "subject"] and m["report"]["logged"]
    assert gm.calls[0]["system"] == B.SYSTEM and gm.calls[1]["system"] == B.SYSTEM


@pytest.mark.asyncio
async def test_an_idea_that_doesnt_fit_is_dropped(tmp_path):
    s, st, gm, agent = world(tmp_path, [draft(), report(fits=False, why="Too loud for this world.")])
    assert await night(st, s, agent) == {"outcome": "dropped", "name": "market-bell", "why": "Too loud for this world."}
    assert st.modules() == []
    (tmp_path / "x").mkdir()
    s2, st2, gm2, agent2 = world(tmp_path / "x", [draft()])
    assert (await night(st2, s2, agent2))["why"] == "the check gave no answer"


@pytest.mark.asyncio
async def test_a_trial_that_goes_wrong_gets_one_fix(tmp_path):
    s, st, gm, agent = world(tmp_path, [draft(code=BROKEN), FITS, report(code=BELL)])
    r = await night(st, s, agent)
    m = st.module(r["module"])
    assert r["clean"] and m["version"] == 2 and m["source"] == BELL and [x["status"] for x in st.modules()] == ["replaced", "waiting"]
    assert "It went wrong: on_tick: line 2: ZeroDivisionError: division by zero." in gm.calls[2]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_a_fix_that_doesnt_help_leaves_the_first_try_and_bad_code_can_be_fixed_too(tmp_path):
    s, st, gm, agent = world(tmp_path, [draft(code=BROKEN), FITS, report(code="import os")])
    r = await night(st, s, agent)
    assert r["clean"] is False and st.module(r["module"])["source"] == BROKEN and len(st.modules()) == 1
    (tmp_path / "b").mkdir()
    s, st, gm, agent = world(tmp_path / "b", [draft(code="import os"), FITS, report(code=BELL)])
    r = await night(st, s, agent)
    assert r["outcome"] == "proposed" and r["clean"] and st.module(r["module"])["version"] == 1
    assert "`import os` isn't allowed" in gm.calls[2]["messages"][0]["content"]
    (tmp_path / "c").mkdir()
    s, st, gm, agent = world(tmp_path / "c", [draft(code="import os"), FITS, report(code="import sys")])
    r = await night(st, s, agent)
    assert r["outcome"] == "failed" and r["why"].startswith("line 1: `import sys` isn't allowed")
    (tmp_path / "d").mkdir()
    s, st, gm, agent = world(tmp_path / "d", [draft(code="import os"), FITS])
    assert (await night(st, s, agent))["why"].startswith("line 1: `import os` isn't allowed")


@pytest.mark.asyncio
async def test_the_builder_can_revise_its_own_and_hears_the_owner(tmp_path):
    s, st, gm, agent = world(tmp_path)
    old = live(st, rule(name="market-bell"), BELL)
    M.disable(st, old["id"], "it rang at night")
    gm.queue(report(action="revise", revises="market-bell", reason="Quiet after dark.", code=BELL), FITS)
    r = await night(st, s, agent)
    assert r["revised"] and st.module(r["module"])["version"] == 2 and st.module(r["module"])["replaces"] == old["id"]
    assert "market-bell (rule; by you; disabled): " in gm.calls[0]["messages"][0]["content"]
    assert "The owner said: it rang at night" in gm.calls[0]["messages"][0]["content"]
    gm.queue(report(action="revise", revises="nothing-here", reason="x", code=BELL))
    assert (await night(st, s, agent, NOW + 86400))["why"] == "there is no module of yours called 'nothing-here' to revise"
    gm.queue(draft(name="market bell"))
    assert await night(st, s, agent, NOW + 2 * 86400) == {"outcome": "failed", "name": "market-bell", "why": "a module with that name already exists"}


@pytest.mark.asyncio
async def test_what_the_builder_is_shown(tmp_path):
    s, st, gm, agent = world(tmp_path, [report(action="nothing", reason="quiet")])
    st.add_memory("a kite to fly over the hill", "wishlist", "thing")
    st.log("garden", plot=1, crop="peas")
    st.log("say", text="private words")
    await night(st, s, agent, time.time())
    prompt = gm.calls[0]["messages"][0]["content"]
    assert B.bible(s) in prompt and "Modules that already exist:\n(none yet)" in prompt and "How a module works:" in prompt
    assert "garden: peas" in prompt and "private words" not in prompt and "Places Pip has only heard of: none" in prompt
    assert "Pip's open wishes: a kite to fly over the hill" in prompt
    assert "Event kinds you can listen for: " + ", ".join(sorted(__import__("app.public_view", fromlist=["x"]).EVENT_FIELDS)) in prompt


def test_the_pieces(tmp_path):
    s, st, gm, agent = world(tmp_path)
    assert B.name_of("Market Bell!") == "market-bell" and B.name_of("9 lives") == "rule-9-lives" and B.name_of("") == "thing"
    assert B.name_of("ab") == "ab-rule"
    man = B.manifest("def on_event(ctx):\n    pass\ndef on_time(ctx):\n    pass\n", "x-rule", ["garden", 3])
    assert man == {"name": "x-rule", "kind": "rule", "api": 1, "hooks": ["on_event", "on_time"], "reads": list(B.RULE_READS),
                   "proposes": list(B.RULE_PROPOSES), "events": ["garden"]}
    assert B.manifest("def on_time(ctx):\n    pass\n", "y", ["garden"])["events"] == []
    assert "subject" not in B.RULE_READS and "places" in B.RULE_READS
    own = tmp_path / "bible.md"
    own.write_text("  A world of glass.  \n")
    s.world_bible_path = str(own)
    assert B.bible(s) == "A world of glass."
    s.world_bible_path = str(tmp_path / "missing.md")
    assert B.bible(s).startswith("This is a small, slow world")
    p = live(st, rule(kind="thing", name="bell-by-pip", subject="Bell"), "x", author="pip")
    w = live(st, rule(name="bells"), "x")
    st.update_module(w["id"], reason="Bells.", note="nice")
    st.update_module(p["id"], note="hidden from the builder")
    assert B.catalogue(st) == "- bell-by-pip (thing, for Bell; by Pip; live): \n- bells (rule; by you; live): Bells. The owner said: nice"


def test_rules_can_read_the_places(tmp_path):
    s, st, gm, agent = world(tmp_path)
    m = live(st, rule(reads=["places"]), "x")
    places = M.context(st, s, m, NOW)["places"]
    assert next(p for p in places if p["key"] == "workshop")["kind"] == "home"
    assert all(set(p) == {"key", "label", "kind"} for p in places)


@pytest.mark.asyncio
async def test_the_nightly_reflection_gives_the_builder_its_turn(tmp_path, monkeypatch):
    s, st, gm, agent = world(tmp_path)
    seen = []

    async def fake_night(state, settings, gm_, runner, now=None):
        seen.append((state is st, runner is agent.runner))
    monkeypatch.setattr(B, "night", fake_night)
    from app import memory as mem

    async def no_reflection(*a, **k):
        return None
    monkeypatch.setattr(mem, "reflect", no_reflection)
    await agent.reflect()
    assert seen == [(True, True)]

    async def broken(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(B, "night", broken)
    await agent.reflect()
    assert st.events(1)[0]["data"]["error"] == "builder: RuntimeError: boom"


def test_the_builder_is_told_the_real_anchors_and_keys():
    text = B.api()
    assert "ANCHORS" not in text and "EVENT_KINDS" not in text
    assert "  home: wall tagged inside, back; surface tagged inside, bench; floor tagged inside; ground tagged outside, yard" in text
    assert "  wild/yard/sight: ground tagged outside" in text and "  market: surface tagged stall, pip, counter; ground tagged outside, square" in text
    assert 'Pip\'s own home is "workshop"' in text


@pytest.mark.asyncio
async def test_a_trial_catches_a_picture_that_only_appears_later_in_the_day(tmp_path):
    s, st, gm, agent = world(tmp_path)
    src = ('def on_install(ctx):\n    return {"schedule": ctx["now"] + 3600}\n'
           'def on_time(ctx):\n    out = {"schedule": ctx["now"] + 3600}\n'
           '    if ctx["now"] >= ctx["state"].get("t", ctx["now"]) and ctx["time"]["hour"] == 17:\n'
           '        out["show"] = [{"id": "lamp", "sprite": {"rows": ["kkkk"] * 4, "palette": {"k": "#fc3"}}, "at": {"type": "wall", "place": "home", "tags": ["window"]}}]\n'
           '    return out\n')
    r = await M.propose(st, s, agent.runner, "world", B.manifest(src, "dusk-lamp", []), src, now=NOW)
    assert r["report"]["unplaced"] == ["lamp: no wall tagged window anchor here"] and r["report"]["clean"] is False
    good = src.replace('"tags": ["window"]', '"tags": ["back"]')
    r = await M.propose(st, s, agent.runner, "world", B.manifest(good, "dusk-lamp-2", []), good, now=NOW)
    assert r["report"]["placed"] == ["lamp: back-wall-by-window at workshop"] and r["report"]["clean"]


# --- word for word -----------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_what_lately_holds_exactly(tmp_path, monkeypatch):
    s, st, gm, agent = world(tmp_path)
    now = time.time()
    for i in range(10):
        st.add_memory(f"wish {i}", "wishlist", "thing")
    st.set_memory_status(next(m["id"] for m in st.memories("wishlist", limit=20) if m["text"] == "wish 0"), "done")
    old = st.log("garden", plot=1, crop="ancient peas")
    st.db.execute("UPDATE events SET ts = ? WHERE id = ?", (now - 2 * 86400 - 5, old))
    st.db.commit()
    for kind, data in (("tick", {"step": 1, "text": "t"}), ("emotion", {"emotion": "joy", "value": 1, "cause": "c"}),
                       ("module", {"name": "m", "text": "a rule spoke"}), ("owner_notice", {"text": "x"}), ("say", {"text": "private"}),
                       ("garden", {"plot": 2, "crop": "beans"}), ("arrived", {"place": "woods", "label": "the woods", "first_time": False}),
                       ("happening", {"id": 1, "title": "A gull", "text": "A gull steals a crust."}),
                       ("reflection", {"summary": "A good day."}), ("neighbor", {"name": "Oriel", "about": "x"}),
                       ("made_work", {"id": 1, "what": "drawing", "title": "Sun", "caption": ""}), ("night_pass", {"decisions": 1})):
        st.log(kind, **data)
    monkeypatch.setattr(__import__("app.worldmap", fromlist=["x"]), "snapshot",
                        lambda *a: {"places": [{"key": "a", "label": "Saltholm", "heard_only": True}, {"key": "b", "label": "Brygdon", "heard_only": False},
                                               {"key": "c", "label": "the Tor", "heard_only": True}]})
    text = B.lately(st, s, now)
    at = lambda: datetime.fromtimestamp(now).strftime("%a %H:%M")
    lines = text.split("\n")
    assert lines[0] == "Lately:" and "ancient peas" not in text and "private" not in text and "a rule spoke" not in text
    assert [l.split(" ", 3)[3] for l in lines[1:8]] == ["garden: beans", "arrived: the woods", "happening: A gull steals a crust.",
                                                        "reflection: A good day.", "neighbor: Oriel", "made_work: Sun", "night_pass: "]
    assert lines[1].startswith(f"- {at()} ") and lines[-2] == "Pip's open wishes: " + "; ".join(f"wish {i}" for i in range(2, 10))
    assert lines[-1] == "Places Pip has only heard of: Saltholm, the Tor"
    st.log("garden", plot=3, crop="x" * 300)
    assert B.lately(st, s, now).split("\n")[8].endswith("garden: " + "x" * 140)
    monkeypatch.setattr(B, "RECENT_EVENTS", 2)
    assert [l.split(": ", 1)[0].split(" ")[-1] for l in B.lately(st, s, now).split("\n")[1:3]] == ["night_pass", "garden"]


def test_lately_when_nothing_happened(tmp_path, monkeypatch):
    s, st, gm, agent = world(tmp_path)
    for e in st.events(100):
        st.db.execute("DELETE FROM events WHERE id = ?", (e["id"],))
    st.db.commit()
    monkeypatch.setattr(__import__("app.worldmap", fromlist=["x"]), "snapshot", lambda *a: {"places": []})
    assert B.lately(st, s, NOW) == "Lately:\n- (quiet)\nPip's open wishes: none\nPlaces Pip has only heard of: none"


@pytest.mark.asyncio
async def test_the_builders_three_questions_word_for_word(tmp_path, monkeypatch):
    s, st, gm, agent = world(tmp_path)
    asked = []
    answers = [{"action": "propose", "name": "dusk", "reason": "Dusk.", "code": BROKEN, "events": []}, {"fits": True, "why": "ok"}, {"code": BELL}]

    async def ask(task, properties, required, purpose, system=None, max_tokens=None):
        asked.append((task, properties, required, purpose, system, max_tokens))
        return answers.pop(0)
    monkeypatch.setattr(agent.gm, "ask", ask)
    monkeypatch.setattr(B, "lately", lambda *a: "LATELY")
    r = await B.night(st, s, agent.gm, agent.runner, NOW)
    draft, fits, fix = asked
    assert draft == (f"What this world is:\n{B.bible(s)}\n\nModules that already exist:\n(none yet)\n\nLATELY\n\nHow a module works:\n{B.api()}\n\n"
                     "You may add one small rule module tonight, revise one of yours (by its name), or add nothing. Fill a real gap: something the "
                     "world is missing that fits it, answering to what has been happening; not a copy of what exists. Most nights, nothing is a fine "
                     "answer. Report action, reason, and for propose or revise the name and the code.", B.DRAFT, ["action", "reason"], "builder", B.SYSTEM, 4000)
    assert fits == (f"What this world is:\n{B.bible(s)}\n\nModules that already exist:\n(none yet)\n\nProposed: dusk: Dusk.\n\nCode:\n{BROKEN}\n\n"
                    "Does this fit the world as described, add something the existing modules don't, and stay quiet enough (rarely speaking to Pip)? "
                    "Report fits (true or false) and why, in one sentence.", {"fits": {"type": "boolean"}, "why": {"type": "string"}}, ["fits", "why"],
                    "builder check", B.SYSTEM, None)
    assert fix == (f"How a module works:\n{B.api()}\n\nYour module dusk (Dusk.):\n{BROKEN}\n\nIt didn't work: {M.trial_text(st.module(1)['report'])}\n"
                   "Fix it. Report the whole corrected code.", {"code": {"type": "string"}}, ["code"], "builder fix", B.SYSTEM, 4000)
    assert set(B.DRAFT) == {"action", "name", "revises", "reason", "events", "code"} and B.DRAFT["action"]["enum"] == ["propose", "revise", "nothing"]
    assert st.module(r["module"])["created_at"] == NOW and st.module(r["module"])["replaces"] == 1


@pytest.mark.asyncio
async def test_the_nights_edges(tmp_path):
    s, st, gm, agent = world(tmp_path)
    gm.queue(report(action="propose", reason="r" * 400))                                          # no code: nothing
    assert await night(st, s, agent) == {"outcome": "nothing", "why": "r" * 300}
    gm.queue(report(action="nothing", reason="", code=BELL))
    assert await night(st, s, agent, NOW + 86400) == {"outcome": "nothing", "why": ""}
    for i, status in enumerate(("proposed", "waiting", "live", "disabled")):
        m = live(st, rule(name=f"bell-{i}"), BELL)
        st.update_module(m["id"], status=status)
        gm.queue(draft(name=f"bell {i}"))
        assert (await night(st, s, agent, NOW + (2 + i) * 86400))["why"] == "a module with that name already exists"
    for i, status in enumerate(("rejected", "replaced")):
        m = live(st, rule(name=f"chime-{i}"), BELL)
        st.update_module(m["id"], status=status)
        gm.queue(draft(name=f"chime {i}", reason="x" * 600), FITS)
        r = await night(st, s, agent, NOW + (10 + i) * 86400)
        assert r["outcome"] == "proposed" and len(st.module(r["module"])["reason"]) == 500
    gm.queue(draft(name="ears", code='def on_event(ctx):\n    return {"log": "heard"}\n', events=["garden"]), FITS)
    r = await night(st, s, agent, NOW + 20 * 86400)
    assert st.module(r["module"])["manifest"]["events"] == ["garden"]
    gm.queue(draft(), report(fits=False, why="w" * 400))
    assert len((await night(st, s, agent, NOW + 21 * 86400))["why"]) == 300


@pytest.mark.asyncio
async def test_revising_finds_its_own_by_name_and_fixes_the_new_version(tmp_path):
    s, st, gm, agent = world(tmp_path)
    old = live(st, rule(name="tide"), BELL)
    st.update_module(old["id"], status="replaced")
    newer = live(st, rule(name="tide"), BELL)
    gm.queue(report(action="revise", name="tide", reason="Better.", code=BROKEN), FITS, report(code=BELL))
    r = await night(st, s, agent)
    first = st.module(r["module"])["replaces"]
    assert st.module(first)["replaces"] == newer["id"] and st.module(r["module"])["source"] == BELL and r["revised"]


def test_names_and_catalogue_edges(tmp_path):
    s, st, gm, agent = world(tmp_path)
    assert B.name_of("abc") == "abc" and B.name_of("a1") == "a1-rule" and B.name_of("a1b") == "a1b" and B.name_of("x" * 60) == "x" * 28
    assert B.name_of("ab" + "c" * 40) == "ab" + "c" * 26
    m = live(st, rule(name="gone"), "x")
    st.update_module(m["id"], status="replaced")
    assert B.catalogue(st) == "(none yet)"


@pytest.mark.asyncio
async def test_more_of_the_nights_edges(tmp_path, monkeypatch):
    s, st, gm, agent = world(tmp_path, [draft(), FITS])
    await night(st, s, agent)
    assert len(gm.calls) == 2                                                                   # a clean trial needs no fix
    gm.queue(report(action="revise", name="no-such", reason="x", code=BELL))
    assert await night(st, s, agent, NOW + 86400) == {"outcome": "failed", "why": "there is no module of yours called 'no-such' to revise"}
    gm.queue(draft(name="bad", code="import os"), FITS, report(code="import sys"))
    r = await night(st, s, agent, NOW + 2 * 86400)
    assert r == {"outcome": "failed", "name": "bad", "why": "line 1: `import sys` isn't allowed; you may import " + ", ".join(M.sandbox.IMPORTS)}
    old = live(st, rule(name="tide"), BELL)
    gm.queue(report(action="revise", revises="tide", reason="Better.", code="import os"), FITS, report(code=BELL))
    r = await night(st, s, agent, NOW + 3 * 86400)
    assert st.module(r["module"])["replaces"] == old["id"] and st.module(r["module"])["version"] == 2


def test_lately_edges(tmp_path, monkeypatch):
    s, st, gm, agent = world(tmp_path)
    monkeypatch.setattr(__import__("app.worldmap", fromlist=["x"]), "snapshot", lambda *a: {"places": []})
    for i in range(9):
        st.add_memory(f"wish {i}", "wishlist", "thing")
    st.set_memory_status(next(m["id"] for m in st.memories("wishlist", limit=20) if m["text"] == "wish 8"), "done")
    st.add_memory("a diary line", "diary")
    e = st.log("garden", plot=1, crop="right on the edge")
    st.db.execute("UPDATE events SET ts = ? WHERE id = ?", (NOW - 2 * 86400, e))
    st.db.commit()
    text = B.lately(st, s, NOW)
    assert "right on the edge" in text and "a diary line" not in text and "wish 8" not in text
    assert "Pip's open wishes: " + "; ".join(f"wish {i}" for i in range(8)) in text
