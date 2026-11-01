"""Slash commands answer from the engine's state: no LLM call, nothing in Pip's inbox, no reply 'from Pip'."""
import time

import pytest

from app import commands
from tests.test_outreach import setup
from tests.test_projects import FixedRng, call, make, report


def ask(st, s, text, now=None):
    return commands.answer(st, s, text, now)


def test_only_slash_words_are_commands(tmp_path):
    s, st, *_ = make(tmp_path)
    for text in ("hello", "", "  ", "what about /status", "/", "/ status", "//status", "/1"):
        assert ask(st, s, text) is None, text
    assert ask(st, s, "/status") is not None
    assert ask(st, s, "  /STATUS  ") == ask(st, s, "/status")                 # case and spaces don't matter


def test_unknown_command_points_to_help(tmp_path):
    s, st, *_ = make(tmp_path)
    r = ask(st, s, "/frobnicate now")
    assert "/frobnicate" in r and "/help" in r


def test_help_lists_every_command(tmp_path):
    s, st, *_ = make(tmp_path)
    r = ask(st, s, "/help")
    for name in commands.NAMES:
        assert f"/{name}" in r
    assert set(commands.NAMES) >= {"help", "status", "items", "garden", "projects", "creations", "notes", "emotions", "usage"}


def test_status_reports_the_agent_and_the_day(tmp_path):
    s, st, *_ = make(tmp_path)
    st.update_agent(activity="working", description="Gear clock: fit the escapement", mood="hopeful",
                    hunger=0.17, energy=0.95, location="workshop")
    r = ask(st, s, "/status")
    assert "working" in r and "Gear clock: fit the escapement" in r and "hopeful" in r
    assert "hunger 17%" in r and "energy 95%" in r and "workshop" in r and "day 1" in r.lower()


def test_status_while_asleep(tmp_path):
    s, st, *_ = make(tmp_path)
    st.update_agent(activity="sleeping", description="asleep")
    assert "sleeping" in ask(st, s, "/status")


def test_items_lists_stock_and_handles_none(tmp_path):
    s, st, *_ = make(tmp_path)
    with st.lock:
        st.db.execute("DELETE FROM items")
        st.db.commit()
    assert "nothing" in ask(st, s, "/items").lower()
    st.add_item("brass wire", 3, "material")
    st.add_item("needle file", 1, "tool")
    r = ask(st, s, "/items")
    assert "brass wire x3 (material)" in r and "needle file x1 (tool)" in r


def test_garden_shows_each_plot(tmp_path):
    s, st, *_ = make(tmp_path)
    st.plant(1, "tomato seeds", "tomato", 60, 3, 0.4)
    st.plant(2, "carrot seeds", "carrot", 0, 2, 0.4)                          # ready now
    r = ask(st, s, "/garden")
    lines = r.splitlines()
    assert any("1" in ln and "tomato" in ln and "growing" in ln and "min" in ln for ln in lines)
    assert any("2" in ln and "carrot" in ln and "ready" in ln for ln in lines)
    assert any("3" in ln and "empty" in ln for ln in lines)


@pytest.mark.asyncio
async def test_projects_shows_progress(tmp_path):
    s, st, gm, agent = make(tmp_path)
    assert "no projects" in ask(st, s, "/projects").lower()
    steps = [{"name": "cut the wheels", "minutes": 60}, {"name": "fit it", "minutes": 60}]
    await call(agent, "start_project", name="gear clock", steps=steps)
    p = st.projects()[0]
    p["stages"][0]["progress"] = 60
    st.update_project(p["id"], stages=p["stages"])
    r = ask(st, s, "/projects")
    assert "gear clock" in r and "50%" in r and "fit it" in r


def test_creations_lists_what_pip_made(tmp_path):
    s, st, *_ = make(tmp_path)
    assert "nothing" in ask(st, s, "/creations").lower()
    st.add_creation("Gear Clock", "keeps even time", None, "sound", {}, {"state": "running"})
    r = ask(st, s, "/creations")
    assert "Gear Clock" in r and "sound" in r and "keeps even time" in r


def test_notes_shows_open_items_by_section(tmp_path):
    s, st, *_ = make(tmp_path)
    st.add_memory("wind the clock", "todo")
    done = st.add_memory("buy brass", "wishlist")
    st.add_memory("a diary line", "diary")
    r = ask(st, s, "/notes")
    assert "wind the clock" in r and "buy brass" in r and "a diary line" not in r      # open todo/wishlist/ambitions by default
    st.resolve_memory(done, "done")
    assert "buy brass" not in ask(st, s, "/notes")
    assert "a diary line" in ask(st, s, "/notes diary")
    assert "wind the clock" not in ask(st, s, "/notes diary")
    assert "no section" in ask(st, s, "/notes bogus").lower()


def test_usage_reports_tokens_against_the_budget(tmp_path):
    s, st, *_ = make(tmp_path, daily_token_budget=5000)
    st.add_usage(1200, 300)
    r = ask(st, s, "/usage")
    assert "1,500" in r and "5,000" in r and "30%" in r


# --- through a channel ----------------------------------------------------------
@pytest.mark.asyncio
async def test_a_command_is_answered_in_the_thread_and_never_reaches_pip(tmp_path):
    s, st, agent, ch = await setup(tmp_path)
    assert await ch.inject("u1", "/items", conversation="thread-1", message_id="c1")
    assert st.pending_inbox() == [] and not agent._wake.is_set()                  # not a visitor message, no wake
    (out, conv, _), = ch.sent
    assert out.kind == "reply" and conv == "thread-1" and "Items" in out.text
    assert not [e for e in st.events(10) if e["kind"] in ("inbox", "outreach")]    # nothing in Pip's feed


@pytest.mark.asyncio
async def test_a_normal_message_still_goes_to_pip(tmp_path):
    s, st, agent, ch = await setup(tmp_path)
    await ch.inject("u1", "how is the clock? /status", message_id="n1")
    assert len(st.pending_inbox()) == 1 and ch.sent == []


@pytest.mark.asyncio
async def test_unknown_commands_are_answered_too(tmp_path):
    s, st, agent, ch = await setup(tmp_path)
    await ch.inject("u1", "/nope", message_id="u2")
    assert st.pending_inbox() == [] and "/help" in ch.sent[0][0].text


@pytest.mark.asyncio
async def test_commands_from_strangers_are_still_dropped(tmp_path):
    s, st, agent, ch = await setup(tmp_path)
    assert await ch.inject("x9", "/status", message_id="s1") is False and ch.sent == []


@pytest.mark.asyncio
async def test_log_mode_answers_nothing_over_the_wire(tmp_path):
    s, st, agent, ch = await setup(tmp_path, mode="log")
    await ch.inject("u1", "/status", message_id="l1")
    assert ch.sent == [] and st.pending_inbox() == []


@pytest.mark.asyncio
async def test_a_failing_channel_does_not_break_the_handler(tmp_path):
    s, st, agent, ch = await setup(tmp_path)
    ch.fail = True
    await ch.inject("u1", "/status", message_id="f1")                             # must not raise
    assert st.pending_inbox() == []
