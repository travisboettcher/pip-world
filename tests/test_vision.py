import base64

import pytest

from app import tools as T
from app.llm.anthropic_backend import _to_api
from app.llm.base import LLMResponse, ToolCall, Usage
from tests.test_art import GOOD
from tests.test_projects import call, make

PNG = ("image/png", b"\x89PNG\r\n\x1a\nfake")


async def painter(tmp_path, **kw):
    s, st, gm, agent = make(tmp_path, **kw)
    agent.tools.update({n: T.REGISTRY[n] for n in ("draw", "look", "write_piece")})
    return s, st, agent


def test_the_anthropic_backend_sends_pictures_inside_the_tool_result():
    msg = {"role": "tool", "results": [{"id": "t1", "name": "draw", "content": "you finish a drawing", "is_error": False, "images": [PNG]},
                                       {"id": "t2", "name": "rest", "content": "resting", "is_error": False}]}
    api = _to_api(msg)
    first, second = api["content"]
    assert first["content"][0] == {"type": "text", "text": "you finish a drawing"}
    assert first["content"][1] == {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                               "data": base64.b64encode(PNG[1]).decode()}}
    assert second["content"] == "resting"                                        # no picture: plain text as before


def test_the_openai_compatible_backend_follows_the_tool_message_with_the_picture():
    from app.llm import openai_compat as oc
    convert = next(getattr(oc, n) for n in dir(oc) if n.startswith("_") and callable(getattr(oc, n)) and "msg" in n.lower() or n == "_to_api")
    out = convert({"role": "tool", "results": [{"id": "t1", "name": "draw", "content": "done", "images": [PNG]}]})
    assert out[0] == {"role": "tool", "tool_call_id": "t1", "content": "done"}
    part = out[1]["content"][1]
    assert out[1]["role"] == "user" and part["type"] == "image_url" and part["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_a_drawing_is_shown_to_the_model_in_the_same_turn_and_can_be_redone(tmp_path):
    s, st, agent = await painter(tmp_path)
    agent.backend.script[:] = [
        LLMResponse("", [ToolCall("d1", "draw", {"title": "The gear clock", "svg": GOOD})], Usage(1, 1)),
        LLMResponse("", [ToolCall("d2", "draw", {"title": "The gear clock", "svg": GOOD.replace("#fc3", "#c33"), "replaces": 1})], Usage(1, 1)),
        LLMResponse("", [], Usage(1, 1)),
    ]
    await agent.tick("test")
    msgs = agent.backend.calls[2]["messages"]                            # user, draw, its result, redo, its result
    second = msgs[2]                                                     # what the model saw right after drawing
    assert second["role"] == "tool" and second["results"][0]["images"][0][0] == "image/png"
    assert "Here is how it came out" in second["results"][0]["content"]
    third = msgs[4]["results"][0]
    assert "you redo #1: The gear clock (version 2)" in third["content"] and third["images"]
    w = st.work(1)
    assert w["revisions"] == 1 and "#c33" in w["body"] and len(st.works()) == 1       # redone in place, not a second picture
    assert any(e["kind"] == "revised_work" for e in st.events(30))
    assert "the first time you looked at your own picture and redid it" in agent._perception("timer", [])


@pytest.mark.asyncio
async def test_redoing_is_limited_checked_and_not_held_back_by_the_gap(tmp_path):
    s, st, agent = await painter(tmp_path)
    await call(agent, "draw", title="Clock", svg=GOOD)
    assert "only just finished" in (await call(agent, "draw", title="Another", svg=GOOD)).text           # a new one waits for the gap
    for n in range(T.MAX_REVISIONS):
        assert "you redo #1" in (await call(agent, "draw", title="Clock", svg=GOOD, replaces=1)).text   # a redo doesn't
    assert "redone #1 3 times already" in (await call(agent, "draw", title="Clock", svg=GOOD, replaces=1)).text
    assert "no drawing #7 to redo" in (await call(agent, "draw", title="x", svg=GOOD, replaces=7)).text
    await call(agent, "write_piece", title="Poem", text="A poem of a few lines that is long enough.")
    assert "no drawing #2 to redo" in (await call(agent, "draw", title="x", svg=GOOD, replaces=2)).text   # a poem isn't a drawing
    bad = await call(agent, "draw", title="Clock", svg='<svg><script>x</script></svg>', replaces=1)
    assert "wasn't accepted" in bad.text or "times already" in bad.text


@pytest.mark.asyncio
async def test_look_shows_an_old_drawing_and_is_limited_per_day(tmp_path):
    s, st, agent = await painter(tmp_path, looks_per_day=2)
    await call(agent, "draw", title="Clock", svg=GOOD, caption="at dusk")
    r = await call(agent, "look", drawing=1)
    assert r.text == "you look at #1, Clock (at dusk)." and r.images[0][1][:4] == b"\x89PNG" and r.followup
    for _ in range(2):  # the daily limit counts the tool events the loop logs
        st.log("tool", tool="look", args={"drawing": 1}, result="you look at #1, Clock.")
    assert "that's enough for now" in (await call(agent, "look", drawing=1)).text
    assert "no drawing #5" in (await call(agent, "look", drawing=5)).text


@pytest.mark.asyncio
async def test_without_vision_pip_is_not_offered_look_and_draw_stays_text_only(tmp_path):
    s, st, agent = await painter(tmp_path)
    agent.backend.vision = False
    agent.ctx.vision = False
    agent.backend.script[:] = [LLMResponse("", [], Usage(1, 1))]
    await agent.tick("test")
    assert "look" not in agent.backend.calls[-1]["tools"]
    r = await call(agent, "draw", title="Clock", svg=GOOD)
    assert r.images == [] and not r.followup and "Here is how it came out" not in r.text
    assert "can't look at pictures" in (await call(agent, "look", drawing=1)).text
    out = await agent._run_tool(ToolCall("x", "draw", {"title": "Two", "svg": GOOD, "replaces": 1}), 0)
    assert "images" not in out                                                       # a non-vision model is never sent a picture
