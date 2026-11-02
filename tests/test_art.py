import time

import pytest
from fastapi.testclient import TestClient

from app import art
from app import tools as T
from app.channels import FakeChannel
from app.config import Settings
from app.llm.fake import FakeBackend
from app.main import create_app
from app.outreach import Outreach
from tests.test_projects import call, make
from tests.test_outreach import daytime

GOOD = ('<svg xmlns="http://www.w3.org/2000/svg" width="999" height="999" viewBox="0 0 5 5"><defs><linearGradient id="sky">'
        '<stop offset="0" stop-color="#9cf"/><stop offset="1" stop-color="#fff"/></linearGradient></defs>'
        '<rect width="400" height="300" fill="url(#sky)"/><circle cx="200" cy="150" r="60" fill="#fc3" stroke="#630" '
        'stroke-width="4" data-x="1"/><path d="M120 220 Q200 120 280 220" fill="none" stroke="#036" stroke-width="5"/>'
        '<text x="200" y="40" text-anchor="middle" font-size="22" fill="#036">the gear clock</text></svg>')


def reject(svg):
    with pytest.raises(art.SvgRejected) as e:
        art.sanitize_svg(svg)
    return str(e.value)


def test_a_good_drawing_is_kept_on_the_fixed_canvas_and_stray_attributes_dropped():
    out = art.sanitize_svg(GOOD)
    assert out.startswith('<svg ') and 'viewBox="0 0 400 300"' in out and 'width="400"' in out and 'height="300"' in out
    assert "999" not in out and "data-x" not in out and 'fill="url(#sky)"' in out and "the gear clock" in out
    assert art.render_png(out)[:4] == b"\x89PNG"


@pytest.mark.parametrize("svg,why", [
    ("<svg><script>alert(1)</script></svg>", "<script> isn't allowed"),
    ('<svg><image href="https://x/y.png"/></svg>', "<image> isn't allowed"),
    ('<svg><use href="#a"/></svg>', "<use> isn't allowed"),
    ("<svg><foreignObject><div/></foreignObject></svg>", "<foreignObject> isn't allowed"),
    ('<svg><rect onclick="x()" width="1" height="1"/></svg>', "'onclick' isn't allowed"),
    ('<svg><rect style="fill:red" width="1" height="1"/></svg>', "'style' isn't allowed"),
    ('<svg xmlns:xlink="http://www.w3.org/1999/xlink"><a xlink:href="javascript:x()"><rect/></a></svg>', "isn't allowed"),
    ('<svg><rect fill="url(https://evil/x)" width="1" height="1"/></svg>', "contains something that isn't allowed"),
    ('<svg><rect fill="url(#nope)" width="1" height="1"/></svg>', "gradients that don't exist"),
    ('<svg><text>x</text><rect d="javascript:alert(1)"/></svg>', "contains something that isn't allowed"),
    ('<!DOCTYPE svg [<!ENTITY a "b">]><svg/>', "no DOCTYPE"),
    ("<svg><rect", "isn't valid SVG"),
    ("<div/>", "outermost element must be <svg>"),
    ("", "empty"),
])
def test_anything_that_could_do_more_than_paint_is_rejected_with_a_reason(svg, why):
    assert why in reject(svg)


def test_size_and_depth_limits():
    assert "too many elements" in reject("<svg>" + "<rect/>" * (art.MAX_ELEMENTS + 1) + "</svg>")
    assert "too big" in reject("<svg><text>" + "x" * (art.MAX_BYTES + 1) + "</text></svg>")
    assert "too deeply" in reject("<svg>" + "<g>" * (art.MAX_DEPTH + 2) + "</g>" * (art.MAX_DEPTH + 2) + "</svg>")


async def drawer(tmp_path, **kw):
    s, st, gm, agent = make(tmp_path, **kw)
    agent.tools.update({n: T.REGISTRY[n] for n in ("draw", "write_piece", "send_postcard")})
    return s, st, agent


@pytest.mark.asyncio
async def test_pip_draws_and_the_picture_is_stored_sanitised_and_remembered(tmp_path):
    s, st, agent = await drawer(tmp_path)
    r = await call(agent, "draw", title="The gear clock", svg=GOOD, caption="at dusk")
    assert "you finish a drawing, #1: The gear clock" in r.text and r.followup and r.images[0][0] == "image/png"   # Pip sees it
    w = st.work(1)
    assert (w["kind"], w["title"], w["caption"]) == ("drawing", "The gear clock", "at dusk") and 'width="400"' in w["body"]
    ev = [e for e in st.events(5) if e["kind"] == "made_work"][0]["data"]
    assert ev["what"] == "drawing" and ev["firsts"][0]["label"] == "the first time you finished a drawing"
    assert st.recall("gear clock")[0]["source"] == "work:drawing"
    assert "Your gallery (latest):\n- #1 The gear clock (drawing)" in agent._perception("timer", [])


@pytest.mark.asyncio
async def test_a_bad_drawing_is_refused_with_what_to_change_and_does_not_use_the_allowance(tmp_path):
    s, st, agent = await drawer(tmp_path)
    r = await call(agent, "draw", title="Sneaky", svg='<svg><script>x</script></svg>')
    assert "wasn't accepted: <script> isn't allowed" in r.text and "Fix it and try again" in r.text and r.followup
    assert st.works() == [] and "give your picture a title" in (await call(agent, "draw", title=" ", svg=GOOD)).text
    r = await call(agent, "draw", title="Broken path", svg='<svg><path d="M 1 1 L"/></svg>')
    assert st.works() == [] or "Broken path" in st.works()[0]["title"]          # a malformed path either renders empty or is refused


@pytest.mark.asyncio
async def test_pictures_and_writing_are_paced(tmp_path):
    s, st, agent = await drawer(tmp_path, works_per_day=2, works_min_gap_minutes=10)
    assert "finish a drawing" in (await call(agent, "draw", title="One", svg=GOOD)).text
    assert "only just finished something" in (await call(agent, "write_piece", title="Two", text="A short poem " * 5)).text
    st.db.execute("UPDATE works SET ts = ts - 3600")
    st.db.commit()
    assert "finish a piece" in (await call(agent, "write_piece", title="Two", text="A short poem about brass, quite long enough.")).text
    st.db.execute("UPDATE works SET ts = ts - 3600")
    st.db.commit()
    assert "as much as you can today (2)" in (await call(agent, "draw", title="Three", svg=GOOD)).text


@pytest.mark.asyncio
async def test_writing_is_kept_for_visitors_separately_from_the_diary(tmp_path):
    s, st, agent = await drawer(tmp_path)
    assert "needs a title" in (await call(agent, "write_piece", title="x", text="too short")).text
    text = "Brass wire bends\nlike a thought that won't settle,\nuntil the file finds the line."
    await call(agent, "write_piece", title="Brass", text=text)
    w = st.work(1)
    assert w["kind"] == "writing" and w["body"] == text and st.memories("diary") == []
    assert "Brass wire bends" in st.recall("settle thought")[0]["text"]
    assert [x["body"] for x in st.works("writing")] == [text] and st.works("drawing") == []


@pytest.mark.asyncio
async def test_a_drawing_can_travel_with_a_postcard_where_the_channel_carries_pictures(tmp_path):
    s, st, agent = await drawer(tmp_path)
    daytime(s)  # postcards are never sent at night
    ch = FakeChannel()
    agent.outreach = Outreach(s, st, [ch], receive=agent.receive)
    agent.ctx.outreach = agent.outreach
    s.outreach = "on"
    await call(agent, "draw", title="The gear clock", svg=GOOD)
    assert "no drawing #9" in (await call(agent, "send_postcard", text="Look what I made today", drawing=9)).text
    ch.capabilities = frozenset({"receive", "threads", "images"})
    r = await call(agent, "send_postcard", text="Look what I made today", drawing=1)
    out = ch.sent[0][0]
    assert "on its way" in r.text and len(out.images) == 1 and out.images[0].data[:4] == b"\x89PNG" and out.images[0].name == "the-gear-clock.png"
    assert "[with a picture: The gear clock]" in st.outreach_rows(1)[0]["text"]
    st.db.execute("UPDATE outreach SET ts = ts - 7200 * 3600")
    st.db.commit()
    ch.capabilities = frozenset({"receive", "threads"})                                # a channel that can't carry pictures
    r = await call(agent, "send_postcard", text="A second, different note entirely", drawing=1)
    assert ch.sent[1][0].images == [] and "the picture can't travel this way" in r.text


def test_the_gallery_api_serves_only_the_sanitised_drawing_with_a_locked_down_policy(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        st = c.app.state.agent.state
        d = st.add_work("drawing", "A circle", art.sanitize_svg(GOOD), "round")
        wr = st.add_work("writing", "A poem", "line one\nline two is here")
        listing = c.get("/works").json()
        assert [w["title"] for w in listing] == ["A poem", "A circle"] and listing[1]["body"] == "" and listing[0]["body"].startswith("line one")
        assert [w["kind"] for w in c.get("/works?kind=drawing").json()] == ["drawing"]
        r = c.get(f"/works/{d}.svg")
        assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
        assert "default-src 'none'" in r.headers["content-security-policy"] and r.headers["x-content-type-options"] == "nosniff"
        assert c.get(f"/works/{d}.png").content[:4] == b"\x89PNG" and c.get(f"/works/{wr}.svg").status_code == 404
        assert c.get("/works/999").status_code == 404 and c.get(f"/works/{wr}").json()["body"].startswith("line one")
