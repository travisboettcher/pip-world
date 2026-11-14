"""Night happenings (rolled when Pip wakes, told as something that happened while it slept) and the seasonal layer (what is likelier when)."""
import random
import time

import pytest

from app import happenings as H
from app.config import Settings
from tests.test_happenings import (NOW, STORY, StubGM, at, create, fresh, force, run, w)


def when(month, day=15, hour=12):
    return time.mktime((2026, month, day, hour, 0, 0, 0, 0, -1))


# --- the seasons (the world's: the sky module reckons them, test_sky.py) ----------------------------------------
@pytest.mark.asyncio
async def test_the_author_is_told_the_season():
    from app.llm.base import LLMResponse, ToolCall, Usage
    from tests.test_gm_prompts import master, task
    gm, b, _ = master(Path_for(), LLMResponse("", [ToolCall("1", "report", {"title": "T", "text": "x"})], Usage(1, 1)))
    await gm.write_happening("garden", "good", "minor", "joy", "", {"period": "morning", "season": "autumn", "names": []}, [])
    assert "It is morning in autumn. Names you may use: none." in task(b)


def Path_for():
    import tempfile
    from pathlib import Path
    return Path(tempfile.mkdtemp())


@pytest.mark.asyncio
async def test_a_prompt_without_a_season_is_as_before():
    from app.llm.base import LLMResponse, ToolCall, Usage
    from tests.test_gm_prompts import master, task
    gm, b, _ = master(Path_for(), LLMResponse("", [ToolCall("1", "report", {"title": "T", "text": "x"})], Usage(1, 1)))
    await gm.write_happening("garden", "good", "minor", "joy", "", {"period": "morning", "names": []}, [])
    assert "It is morning. Names you may use: none." in task(b)


def test_create_gives_the_author_the_season(tmp_path, monkeypatch):
    s, st = fresh(tmp_path)
    force(monkeypatch)
    gm = StubGM(STORY)
    run(create(st, s, gm, w(season="winter"), NOW, "x", random.Random(1)))
    assert gm.calls[0][5]["season"] == "winter" and "night" not in gm.calls[0][5]
    gm = StubGM(STORY)
    run(create(st, s, gm, w(season=None), NOW, "y", random.Random(1)))
    assert "season" not in gm.calls[0][5] or gm.calls[0][5]["season"] is None


# --- night happenings --------------------------------------------------------------------------------------------
def slept(st, hours=8.0, woke_at=None, early=False):
    """Pip went to bed and woke: the `woke` event the engine logs, and the agent awake again."""
    woke_at = woke_at or at(6, 0)
    st.update_agent(activity="idle")
    eid = st.log("woke", hours=hours, early=early)
    st.db.execute("UPDATE events SET ts = ? WHERE id = ?", (woke_at, eid))
    st.db.commit()
    return eid


def night(tmp_path, **kw):
    kw.setdefault("happenings_chance", 1.0)
    return fresh(tmp_path, **kw)


def stepped(s, st, gm, now):
    return run(H.step(st, s, gm, now))


def test_a_night_happening_is_told_as_something_that_happened_while_pip_slept(tmp_path, monkeypatch):
    s, st = fresh(tmp_path)
    force(monkeypatch)
    gm = StubGM(STORY)
    row = run(create(st, s, gm, w(period="morning"), at(6, 1), "night", night=True))
    facts = gm.calls[0][5]
    assert facts["night"] is True and facts["period"] == "morning" and row["context"]["night"] is True


@pytest.mark.asyncio
async def test_the_author_is_told_it_happened_in_the_night():
    from app.llm.base import LLMResponse, ToolCall, Usage
    from tests.test_gm_prompts import master, task
    gm, b, _ = master(Path_for(), LLMResponse("", [ToolCall("1", "report", {"title": "T", "text": "x"})], Usage(1, 1)))
    await gm.write_happening("pantry", "bad", "minor", "joy", "", {"period": "morning", "names": [], "night": True}, [])
    p = task(b)
    assert "It happened in the night, while Pip slept, and Pip finds out on waking: tell it in the past tense.\n" in p
    gm2, b2, _ = master(Path_for(), LLMResponse("", [ToolCall("1", "report", {"title": "T", "text": "x"})], Usage(1, 1)))
    await gm2.write_happening("pantry", "bad", "minor", "joy", "", {"period": "morning", "names": []}, [])
    assert "in the night" not in task(b2)


def test_the_environment_settings(monkeypatch):
    assert Settings().happenings_seasons is True and Settings().hemisphere == "north"
    for k in ("HAPPENINGS_SEASONS", "HEMISPHERE"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env()
    assert s.happenings_seasons is True and s.hemisphere == "north"
    monkeypatch.setenv("HAPPENINGS_SEASONS", "off")
    monkeypatch.setenv("HEMISPHERE", "South")
    s = Settings.from_env()
    assert s.happenings_seasons is False and s.hemisphere == "south"
    monkeypatch.setenv("HAPPENINGS_SEASONS", "maybe")
    monkeypatch.setenv("HEMISPHERE", "sideways")
    s = Settings.from_env()
    assert s.happenings_seasons is True and s.hemisphere == "north"


