"""Voices (0.27.0): general hooks for things Pip can talk to, owned wholly by modules. A module declares `voices` (named, somewhere), hears
what Pip says to them (`on_message`), asks the model for words (`ask`, answered later in `on_answer`) and speaks as them (`speak`).
The engine only routes words, makes the model call, enforces limits and records what was said."""
import time

import pytest

from app import modules as M
from app import places
from tests.test_modules import NOW, live, modular, rule
from tests.test_projects import call


class Words:
    """A stand-in model: answers every ask with a numbered line, and remembers the prompts."""
    def __init__(self, text="Tick, tock.", fail=False):
        self.prompts, self.text, self.fail = [], text, fail

    async def words(self, prompt, most):
        self.prompts.append((prompt, most))
        return None if self.fail else self.text


WELL = ("def on_install(ctx):\n    return {'voices': [{'name': 'the Old Well', 'at': 'home', 'about': 'a well that talks back'}]}\n"
        "def on_message(ctx):\n    m = ctx['message']\n"
        "    return {'state': {'heard': ctx['state'].get('heard', []) + [m['text']]}, 'ask': {'prompt': 'Echo: ' + m['text'], 'purpose': 'reply'}}\n"
        "def on_answer(ctx):\n    a = ctx['answer']\n"
        "    if not a['text']:\n        return {}\n"
        "    return {'speak': {'as': 'the Old Well', 'text': a['text'], 'to_pip': a['purpose'] == 'reply'}}\n")
WELL_MAN = rule(name="old-well", hooks=["on_install", "on_message", "on_answer"], proposes=["voices", "ask", "speak", "state"])


async def well(tmp_path, **kw):
    s, st, agent = modular(tmp_path, **kw)
    m = live(st, WELL_MAN, WELL)
    await M.call(st, s, agent.runner, m, "on_install", NOW)
    return s, st, agent, st.module(m["id"])


# --- declaring voices --------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_module_declares_voices_and_pip_hears_who_is_there(tmp_path):
    s, st, agent, m = await well(tmp_path)
    assert m["voices"] == [{"name": "the Old Well", "at": "home", "about": "a well that talks back"}]
    assert M.voice_named(st, "old well")[1]["name"] == "the Old Well" and M.voice_named(st, "THE OLD WELL")[0]["id"] == m["id"]
    assert M.voice_named(st, "the river") is None
    assert M.voices_here(st) == ["Here to talk to (say with `to`): the Old Well (a well that talks back)."]
    st.update_agent(location="Brygdon")
    assert M.voices_here(st) == []
    M.disable(st, m["id"])
    assert M.voice_named(st, "the old well") is None


def test_voices_are_checked(tmp_path):
    s, st, agent = modular(tmp_path)
    st.add_character("Oriel Vantosh", "neighbor", None, "x", 60, NOW)
    m = live(st, rule(proposes=["voices"]), "x")
    other = live(st, rule(name="ferry", proposes=["voices"]), "x")
    M.apply(st, other, M.plan(st, other, {"voices": [{"name": "the Ferryman", "at": "Brygdon"}]}, NOW, "on_tick"), NOW)
    def why(v):
        with pytest.raises(M.Refused) as e:
            M.plan(st, m, {"voices": v}, NOW, "on_tick")
        return str(e.value)
    shape = "`voices` is a list of up to 4 {name, at, about?}: at is \"home\", \"subject\" or a place's key"
    for bad in ({"name": "x"}, [{"name": "x"}], [{"name": "", "at": "home"}], [{"name": "x" * 41, "at": "home"}], [{"name": "Bo", "at": 3}],
                [{"name": "Bo", "at": "home", "about": "x" * 201}], [{"name": f"V{i}", "at": "home"} for i in range(5)]):
        assert why(bad) == shape, bad
    assert why([{"name": "oriel vantosh", "at": "home"}]) == "someone called oriel vantosh is already in the world"
    assert why([{"name": "The ferryman", "at": "home"}]) == "someone called The ferryman is already in the world"
    assert why([{"name": "Bo", "at": "home"}, {"name": "bo", "at": "home"}]) == "two voices can't share a name"
    assert M.plan(st, other, {"voices": [{"name": "the Ferryman", "at": "Brygdon"}]}, NOW, "on_tick")      # its own: fine
    assert M.plan(st, m, {"voices": []}, NOW, "on_tick") == [("voices", [])]
    assert "voices" not in M.PIP_PROPOSES and "ask" not in M.PIP_PROPOSES and "speak" not in M.PIP_PROPOSES


def test_hearing_and_asking_need_their_proposals():
    with pytest.raises(M.Refused) as e:
        M.check_manifest(rule(hooks=["on_message"], proposes=["state"]), "world")
    assert str(e.value) == "`on_message` hears what Pip says to the module's voices: it needs `voices` among what it proposes"
    with pytest.raises(M.Refused) as e:
        M.check_manifest(rule(hooks=["on_answer"], proposes=["state"]), "world")
    assert str(e.value) == "`on_answer` gets the words it asked for: it needs `ask` among what it proposes"
    assert M.check_manifest(WELL_MAN, "world")["hooks"] == ["on_install", "on_message", "on_answer"]


# --- a conversation ----------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pip_talks_to_a_voice_and_it_answers_later(tmp_path):
    s, st, agent, m = await well(tmp_path)
    r = await call(agent, "say", text="Hello, well.", to="the old well")
    assert r.text == "said it to the Old Well; it will answer in a moment"
    said = next(e["data"] for e in st.events(5) if e["kind"] == "say")
    assert said["to_name"] == "the Old Well" and said["text"] == "Hello, well."
    assert st.module(m["id"])["heard"][0]["text"] == "Hello, well." and st.module(m["id"])["heard"][0]["to"] == "the Old Well"
    assert await M.step(st, s, agent.runner, NOW + 60) is False                                       # it hears, and asks
    m = st.module(m["id"])
    assert m["heard"] == [] and m["state"]["heard"] == ["Hello, well."] and m["asks"][0]["prompt"] == "Echo: Hello, well."
    gm = Words("Well, hello.")
    assert await M.answer(st, s, gm, agent.runner, NOW + 120) is True                                   # the answer, spoken to Pip, wakes it
    assert gm.prompts[0][0].startswith("Echo: Hello, well.") and gm.prompts[0][1] == 300
    spoke = next(e["data"] for e in st.events(5) if e["kind"] == "companion")
    assert {k: spoke[k] for k in ("name", "text", "reply", "module")} == {"name": "the Old Well", "text": "Well, hello.", "reply": True, "module": "old-well"}
    assert st.module(m["id"])["asks"] == [] and await M.answer(st, s, gm, agent.runner, NOW + 180) is False


@pytest.mark.asyncio
async def test_a_voice_can_only_be_heard_where_it_is(tmp_path):
    s, st, agent, m = await well(tmp_path)
    st.update_agent(location="Brygdon")
    r = await call(agent, "say", text="Hello?", to="the old well")
    assert r.text == "the Old Well can't hear you from here" and r.followup and st.module(m["id"])["heard"] == []


@pytest.mark.asyncio
async def test_a_voice_without_ears_hears_nothing_and_a_failed_ask_answers_empty(tmp_path):
    s, st, agent = modular(tmp_path)
    mute = live(st, rule(name="statue", hooks=["on_install"], proposes=["voices"]),
                "def on_install(ctx):\n    return {'voices': [{'name': 'the Statue', 'at': 'home'}]}\n")
    await M.call(st, s, agent.runner, mute, "on_install", NOW)
    r = await call(agent, "say", text="Nice hat.", to="the statue")
    assert r.text == "said it to the Statue" and st.module(mute["id"])["heard"] == []
    (tmp_path / "b").mkdir()
    s, st, agent, m = await well(tmp_path / "b")
    await call(agent, "say", text="Anyone?", to="the old well")
    await M.step(st, s, agent.runner, NOW + 60)
    assert await M.answer(st, s, Words(fail=True), agent.runner, NOW + 120) is False
    assert st.module(m["id"])["asks"] == [] and not [e for e in st.events(5) if e["kind"] == "companion"]
    await call(agent, "say", text="Anyone at all?", to="the old well")
    await M.step(st, s, agent.runner, NOW + 180)
    assert await M.answer(st, s, None, agent.runner, NOW + 240) is False                               # no model: an empty answer


@pytest.mark.asyncio
async def test_a_voices_words_reach_pip_like_anyones(tmp_path):
    s, st, agent, m = await well(tmp_path)
    M.apply(st, m, M.plan(st, m, {"speak": {"as": "the Old Well", "text": "Drip."}}, NOW, "on_tick"), NOW)
    assert next(e["data"] for e in st.events(3) if e["kind"] == "companion")["reply"] is False
    assert '- the Old Well said: "Drip."' in agent._perception("tick", [])


# --- speaking and asking are checked -----------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_speak_and_ask_are_checked_and_capped(tmp_path):
    s, st, agent, m = await well(tmp_path)
    def why(result, mod=None):
        with pytest.raises(M.Refused) as e:
            M.plan(st, mod or st.module(m["id"]), result, NOW, "on_tick")
        return str(e.value)
    assert why({"speak": {"as": "the Ferryman", "text": "hi"}}) == "it can only speak as its own voices: the Old Well"
    assert why({"speak": {"as": "the Old Well", "text": ""}}) == "`speak` is {as, text, to_agent?}: text is a line of up to 400 characters"
    assert why({"speak": {"as": "the Old Well", "text": "x" * 401}}).startswith("`speak` is {as, text")
    assert why({"speak": "hi"}).startswith("`speak` is {as, text")
    assert M.plan(st, st.module(m["id"]), {"voices": [{"name": "Bucket", "at": "home"}], "speak": {"as": "Bucket", "text": "Clank."}}, NOW, "on_tick")
    assert why({"ask": {"prompt": ""}}) == "`ask` is {prompt, purpose?, most?}: a prompt of up to 2000 characters, at most 600 characters back"
    assert why({"ask": {"prompt": "x" * 2001}}).startswith("`ask` is {prompt")
    assert why({"ask": {"prompt": "hi", "most": 601}}).startswith("`ask` is {prompt")
    assert why({"ask": {"prompt": "hi", "purpose": "x" * 41}}).startswith("`ask` is {prompt")
    asks = [{"id": i, "prompt": "p", "purpose": "", "most": 300, "ts": NOW} for i in range(M.ASKS_WAITING)]
    st.update_module(m["id"], asks=asks)
    assert why({"ask": {"prompt": "hi"}}) == f"it already has {M.ASKS_WAITING} questions waiting for words"
    st.update_module(m["id"], asks=[], budget={"day": M._day(NOW), "ask": M.PER_DAY["ask"], "speak": M.PER_DAY["speak"]})
    assert why({"ask": {"prompt": "hi"}}) == f"it has used today's {M.PER_DAY['ask']} `ask`"
    assert why({"speak": {"as": "the Old Well", "text": "hi"}}) == f"it has used today's {M.PER_DAY['speak']} `speak`"
    assert M.limits({"author": M.SHIPPED})["ask"] > M.PER_DAY["ask"]


@pytest.mark.asyncio
async def test_the_model_is_asked_plainly_and_its_words_trimmed(tmp_path):
    from app.gm import GameMaster as GM
    s, st, agent = modular(tmp_path)
    seen = []
    class GMish(GM):
        def __init__(self):
            pass
        async def ask(self, task, properties, required, purpose, system=None, max_tokens=None):
            seen.append((task, purpose))
            return {"text": '  "' + "word " * 100 + '"  '}
    out = await GMish().words("Say hello as a teapot.", 40)
    assert len(out) <= 40 and not out.startswith(('"', " ")) and seen[0][1] == "module_words" and seen[0][0].startswith("Say hello as a teapot.")
    class Silent(GMish):
        async def ask(self, *a, **k):
            return None
    assert await Silent().words("x", 40) is None


# --- the trial ---------------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_trial_says_hello_and_shows_what_it_would_ask(tmp_path):
    s, st, agent = modular(tmp_path, modules_approval="owner")
    r = await M.propose(st, s, agent.runner, "world", WELL_MAN, WELL, "a talking well", now=NOW)
    rep = r["report"]
    assert rep["clean"] and rep["asked"] == ["Echo: Hello."] and rep["spoken"] == ["the Old Well: (the model's words)"]
    assert "It would ask the model: Echo: Hello." in M.trial_text(rep) and "It would say: the Old Well: (the model's words)" in M.trial_text(rep)


# --- word for word -----------------------------------------------------------------------------------------------------------
def test_voices_at_their_limits_word_for_word(tmp_path):
    from tests.test_world_view import clock
    s, st, agent = modular(tmp_path)
    c = clock(st)
    st.add_character("Gear Clock", "creation", c["id"], "x", 60, NOW)                     # the clock's own old character
    other = st.add_creation("Bell", "a bell", None, "sound", {"capabilities": {}, "quirks": []}, {})
    st.add_character("Bell", "creation", other["id"], "x", 60, NOW)
    thing = live(st, rule(kind="thing", name="clock-voice", subject="Gear Clock", proposes=["voices"]), "x")
    four = [{"name": "G", "at": "home"}, {"name": "x" * 40, "at": " " + "y" * 70, "about": "z" * 200}, {"name": "Gear Clock", "at": "subject"},
            {"name": "Tock", "at": "home", "about": " ticks "}]
    (_, got), = M.plan(st, thing, {"voices": four}, NOW, "on_tick")
    assert got == [{"name": "G", "at": "home", "about": ""}, {"name": "x" * 40, "at": "y" * 60, "about": "z" * 200},
                   {"name": "Gear Clock", "at": "subject", "about": ""}, {"name": "Tock", "at": "home", "about": "ticks"}]
    with pytest.raises(M.Refused) as e:
        M.plan(st, thing, {"voices": [{"name": "Bell", "at": "home"}]}, NOW, "on_tick")                # another creation's: taken
    assert str(e.value) == "someone called Bell is already in the world"
    with pytest.raises(M.Refused):
        M.plan(st, thing, {"voices": [{"name": "Bo", "at": "home"}, {"name": "BO", "at": "home"}]}, NOW, "on_tick")
    rule_m = live(st, rule(name="no-subject", proposes=["voices"]), "x")
    with pytest.raises(M.Refused):
        M.plan(st, rule_m, {"voices": [{"name": "Gear Clock", "at": "home"}]}, NOW, "on_tick")        # not its creation: taken
    M.apply(st, thing, [("voices", got)], NOW)
    off = live(st, rule(name="gone", proposes=["voices"]), "x")
    st.update_module(off["id"], voices=[{"name": "Ghost", "at": "home", "about": ""}], status="disabled")
    assert M.plan(st, rule_m, {"voices": [{"name": "Ghost", "at": "home"}]}, NOW, "on_tick")          # a voice that isn't live is free
    assert M.voices_here(st) == ["Here to talk to (say with `to`): G; Gear Clock; Tock (ticks)."]
    assert M.voice_named(st, "") is None and M.voice_named(st, None) is None


def test_speak_and_ask_at_their_limits(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(proposes=["voices", "speak", "ask"]), "x")
    voices = [{"name": "Bo", "at": "home", "about": ""}]
    st.update_module(m["id"], voices=voices)
    m = st.module(m["id"])
    assert M.plan(st, m, {"speak": {"as": "bo", "text": "w" * 400}}, NOW, "on_tick") == [("speak", {"name": "Bo", "text": "w" * 400, "to_agent": False})]
    assert M.plan(st, m, {"speak": {"as": "Bo", "text": " hi ", "to_pip": 1}}, NOW, "on_tick") == [("speak", {"name": "Bo", "text": "hi", "to_agent": False})]
    for bad in ({"as": "Bo"}, {"text": "hi"}, {"as": "Bo", "text": 3}):
        with pytest.raises(M.Refused):
            M.plan(st, m, {"speak": bad}, NOW, "on_tick")
    with pytest.raises(M.Refused) as e:
        M.plan(st, live(st, rule(name="mute", proposes=["voices", "speak"]), "x"), {"speak": {"as": "Bo", "text": "hi"}}, NOW, "on_tick")
    assert str(e.value) == "it can only speak as its own voices: it has none"
    st.update_module(m["id"], voices=voices + [{"name": "Al", "at": "home", "about": ""}])
    with pytest.raises(M.Refused) as e:
        M.plan(st, st.module(m["id"]), {"speak": {"as": "Cy", "text": "hi"}}, NOW, "on_tick")
    assert str(e.value) == "it can only speak as its own voices: Bo, Al"
    assert M.plan(st, m, {"ask": {"prompt": "p" * 2000, "purpose": "q" * 40, "most": 20}}, NOW, "on_tick") == \
        [("ask", {"prompt": "p" * 2000, "purpose": "q" * 40, "most": 20})]
    assert M.plan(st, m, {"ask": {"prompt": " p "}}, NOW, "on_tick") == [("ask", {"prompt": "p", "purpose": "", "most": 300})]
    for bad in ({"prompt": "p", "most": 19}, {"prompt": 3}, "p", {"prompt": "p", "purpose": 3}):
        with pytest.raises(M.Refused):
            M.plan(st, m, {"ask": bad}, NOW, "on_tick")


@pytest.mark.asyncio
async def test_hearing_keeps_the_last_five_words_for_word(tmp_path):
    s, st, agent, m = await well(tmp_path)
    v = m["voices"][0]
    for i in range(7):
        assert M.hear(st, st.module(m["id"]), v, ("x" * 1001) if i == 6 else f"line {i}", NOW + i) is True
    heard = st.module(m["id"])["heard"]
    assert [h["text"] for h in heard] == ["line 2", "line 3", "line 4", "line 5", "x" * 1000]
    assert heard[0] == {"to": "the Old Well", "text": "line 2", "from": "Pip", "ts": NOW + 2}
    t0 = time.time()
    M.hear(st, st.module(m["id"]), v, "now")
    assert t0 <= st.module(m["id"])["heard"][-1]["ts"] <= time.time()


@pytest.mark.asyncio
async def test_answers_go_to_every_live_module_that_asked(tmp_path):
    s, st, agent = modular(tmp_path)
    asks = lambda *ps: [{"id": i + 1, "prompt": p, "purpose": "reply", "most": 300, "ts": NOW} for i, p in enumerate(ps)]
    src = "def on_answer(ctx):\n    return {'speak': {'as': 'Bo', 'text': ctx['answer']['text'] or 'nothing', 'to_pip': ctx['answer']['purpose'] == 'reply'}}\n"
    quiet = live(st, rule(name="asks-nothing", hooks=["on_answer"], proposes=["ask"]), "def on_answer(ctx):\n    return {}\n")
    talker = live(st, rule(name="talker", hooks=["on_answer"], proposes=["ask", "voices", "speak"]), src, author=M.SHIPPED)
    st.update_module(talker["id"], voices=[{"name": "Bo", "at": "home", "about": ""}], asks=asks("one", "two"))
    gone = live(st, rule(name="gone", hooks=["on_answer"], proposes=["ask", "voices", "speak"]), src)
    st.update_module(gone["id"], status="disabled", asks=asks("never"))
    world = live(st, rule(name="world-talker", hooks=["on_answer"], proposes=["ask", "voices", "speak"]), src)
    st.update_module(world["id"], voices=[{"name": "Bo2", "at": "home", "about": ""}], asks=asks("not without a runner"))
    words = Words("Yes.")
    assert await M.answer(st, s, words, None, NOW) is True                                          # no runner: only the engine's own
    assert [p for p, _ in words.prompts] == ["one", "two"] and st.module(talker["id"])["asks"] == []
    assert st.module(gone["id"])["asks"] and st.module(world["id"])["asks"]
    assert [e["data"]["text"] for e in st.events(5) if e["kind"] == "companion"] == ["Yes.", "Yes."]
    st.update_module(talker["id"], asks=[{**asks("three")[0], "purpose": "chatter"}, *asks("four")[1:]])
    assert await M.answer(st, s, words, None, NOW + 1) is False                                     # chatter doesn't wake Pip
    st.update_module(talker["id"], asks=asks("five", "six")[:1] + [{**asks("x", "six")[1], "purpose": "chatter"}])
    assert await M.answer(st, s, words, None, NOW + 2) is True                                      # any answer to Pip wakes it
    st.update_module(talker["id"], asks=asks("seven"))
    assert await M.answer(st, s, None, agent.runner, NOW + 3) is True                                # no model: an empty answer
    assert [e["data"]["text"] for e in st.events(3) if e["kind"] == "companion"][0] == "nothing"
    assert st.module(quiet["id"])["asks"] == []
