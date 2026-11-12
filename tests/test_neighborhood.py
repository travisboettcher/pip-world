"""The neighbourhood (docs/DESIGN-world-packs.md, phase 5b): the shipped `neighborhood` module invents the neighbour once, through a
structured ask, and asks them to write first now and then. Letters themselves, and a neighbour's answers, stay the engine's."""
import time

import pytest

from app import modules as M
from app import neighbors as nb
from app.llm.base import LLMResponse, Usage
from app.text import clip
from tests.test_neighbor import INVENTED, MENTION, SALTHOLM, neighbor
from tests.test_projects import make, report


def module(st, s, **params):
    from tests.test_modules import live
    man, src = M.library("neighborhood")
    man.pop("reason", None)
    defaults = {"invent": s.neighbor, "every_hours": s.neighbor_writes_every_hours}
    return live(st, {**man, "params": {**man["params"], **defaults, **params}}, src, author=M.SHIPPED)


async def invent(st, s, agent, now=None):
    """The module's turn (it asks who the neighbour is), then the model's answer."""
    now = now or time.time()
    m = M.live_named(st, "neighborhood") or module(st, s)
    st.update_module(m["id"], due=now)
    await M.step(st, s, agent.runner, now)
    await M.answer(st, s, agent.gm, agent.runner, now)
    return M.live_named(st, "neighborhood")


async def test_the_neighbour_is_invented_once_and_writes_first(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**INVENTED)], neighbor=True)
    now = time.time()
    await invent(st, s, agent, now)
    (ch,) = st.characters("neighbor")
    assert (ch["name"], ch["about"], ch["persona"]) == ("Marigold", "Lives past the hedge; keeps bees.", INVENTED["persona"])
    (first,) = st.letters()
    assert first["sender"] == "Marigold" and first["recipient"] == "Pip" and first["text"] == INVENTED["letter"]
    assert now + 0.25 * 0.7 * 120 * 60 <= first["deliver_at"] <= now + 0.25 * 1.3 * 120 * 60          # soon-ish
    assert next(e["data"] for e in st.events(limit=5) if e["kind"] == "neighbor") == {"name": "Marigold", "about": ch["about"]}
    assert ch["chatter_minutes"] == s.neighbor_writes_every_hours * 60 and ch["next_chatter_at"] == nb.NOT_YET
    await invent(st, s, agent, now + 60)
    assert len(gm.calls) == 1 and len(st.characters("neighbor")) == 1


async def test_what_the_model_is_asked(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**{**INVENTED, "letter": SALTHOLM, "mentions_place": MENTION})], neighbor=True,
                            wild_places=["woods"])
    for i in range(6):
        st.add_creation(f"thing {i}", "made", None, "fine", {"capabilities": {}}, {})
    await invent(st, s, agent, 1000.0)
    task = gm.calls[0]["messages"][0]["content"]
    assert task.startswith("Pip's world so far: Pip lives alone in a workshop with a garden; Pip has made "
                           "thing 0, thing 1, thing 2, thing 3, thing 4\n\nSomeone lives near Pip and is about to write to Pip")
    assert task.endswith("visiting themselves.\nOnly if your words point Pip to a place it could go that isn't one of these: the woods, "
                         "give `mentions_place` (`place`: the destination as you said it; `there`: what you say is there, under 120 "
                         "characters; `distance`: near, far or very far, as you'd put it; `items`: things you say can be had there). Not your "
                         "own home, not landscape you just pass through.")
    assert st.place_row("Saltholm")["mentions"][0]["by"] == "Marigold" and st.place_row("Saltholm")["created_at"] == 1000.0


async def test_a_long_answer_is_trimmed(tmp_path):
    raw = {**INVENTED, "name": "N" * 41, "persona": "p" * 801, "about": "a" * 161, "letter": "l" * 1201}
    s, st, gm, agent = make(tmp_path, [report(**raw)], neighbor=True)
    await invent(st, s, agent)
    (ch,) = st.characters("neighbor")
    assert ch["name"] == "N" * 40 and ch["persona"] == "p" * 800 and ch["about"] == "a" * 160 and st.letters()[0]["text"] == "l" * 1200


@pytest.mark.parametrize("script", [[LLMResponse("no", [], Usage(1, 1))], [report(**{**INVENTED, "letter": ""})], [report(**{**INVENTED, "name": ""})],
                                    [report(**{**INVENTED, "name": "pip"})], []])
async def test_no_neighbour_without_a_good_answer_and_another_try_in_an_hour(tmp_path, script):
    s, st, gm, agent = make(tmp_path, script, neighbor=True)
    now = time.time()
    m = await invent(st, s, agent, now)
    assert st.characters() == [] and m["due"] == pytest.approx(now + 3600)


async def test_without_a_gm_nobody_is_invented(tmp_path):
    s, st, gm, agent = make(tmp_path, neighbor=True)
    agent.gm = None
    await invent(st, s, agent)
    assert st.characters() == []


async def test_a_world_without_a_neighbour_never_asks(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**INVENTED)], neighbor=False)
    m = await invent(st, s, agent)
    assert gm.calls == [] and st.characters() == [] and m["asks"] == []


async def test_the_neighbour_writes_first_now_and_then(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="The bees are busy.", gist="Bees.")], neighbor=True)
    ch = neighbor(st, s)
    now = time.time()
    m = module(st, s, every_hours=10)
    st.update_module(m["id"], due=now)
    await M.step(st, s, agent.runner, now)
    due = st.module(m["id"])["state"]["due"]["Marigold"]
    assert now + 0.7 * 36000 <= due <= now + 1.3 * 36000 and st.module(m["id"])["due"] == due      # a while off
    st.update_module(m["id"], due=due)
    await M.step(st, s, agent.runner, due)                                                         # due: the module asks her to write
    assert st.characters("neighbor")[0]["next_chatter_at"] == due
    assert await nb.step(st, s, agent.gm, __import__("random").Random(1), due) is False            # the engine writes it
    (lt,) = st.letters()
    assert lt["sender"] == "Marigold" and lt["text"] == "The bees are busy." and st.characters("neighbor")[0]["next_chatter_at"] == nb.NOT_YET
    later = st.module(m["id"])["state"]["due"]["Marigold"]
    assert due + 0.7 * 36000 <= later <= due + 1.3 * 36000


def test_the_module_ships_with_the_settings_as_its_params():
    from app.config import Settings
    man, _ = M.library("neighborhood")
    assert M.settings_params(Settings(neighbor=False, neighbor_writes_every_hours=12), "neighborhood", man["params"]) == {"invent": False, "every_hours": 12}
    assert "neighborhood" in M.RULES
