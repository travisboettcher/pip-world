import time

import pytest

from app import art
from app import tools as T
from app import world_view as WV
from tests.test_projects import call, make
from tests.test_world_view import clock

ROWS = ["..kk..", ".kyyk.", "kyyyyk", ".kyyk.", "..kk.."]
PAL = {"k": "#2a1f1a", "y": "#FC3"}


def reject(rows, palette=PAL):
    with pytest.raises(art.SvgRejected) as e:
        art.clean_pixels(rows, palette)
    return str(e.value)


# --- the grid ---------------------------------------------------------------------------------------------------------------
def test_a_pixel_picture_is_kept_as_written_with_colours_lowercased():
    rows, pal = art.clean_pixels(ROWS, PAL)
    assert rows == ROWS and pal == {"k": "#2a1f1a", "y": "#fc3"}
    assert art.clean_pixels(["abcd"] * 4, {"a": "#000", "b": "#111", "c": "#222", "d": " #333 "})[1]["d"] == "#333"


def test_the_grid_has_limits_and_every_refusal_says_what_to_fix():
    assert "4 to 32 rows tall; this one has 3" in reject(["kkkk"] * 3)
    assert "this one has 33" in reject(["kkkk"] * 33)
    assert art.clean_pixels(["k" * 32] * 32, PAL)[0][0] == "k" * 32 and art.clean_pixels(["kkkk"] * 4, PAL)
    assert "same length, 4 to 32" in reject(["kkk"] * 4)
    assert "same length" in reject(["k" * 33] * 4)
    assert "same length" in reject(["kkkk", "kkkk", "kkk", "kkkk"])
    assert reject("kkkk") == '`pixels` is a list of rows, each a string of palette letters ("." for nothing)' and "list of rows" in reject(["kkkk", 5, "kkkk", "kkkk"])
    assert art.clean_pixels(["kkkk\n"] * 4, PAL)[0] == ["kkkk"] * 4 and art.clean_pixels(["kkXX"] * 4, {"k": "#000", "X": "#fff"})[0] == ["kkXX"] * 4 and "aren't in your palette" in reject(["kk  "] * 4)
    assert "maps up to 16 single letters" in reject(ROWS, {})
    assert "maps up to 16" in reject(ROWS, "#000") and "maps up to 16" in reject(ROWS, {chr(97 + i): "#000" for i in range(17)})
    full = {**PAL, **{chr(97 + i): "#000" for i in range(15) if chr(97 + i) not in PAL}}
    assert len(full) == art.PALETTE_MAX and art.clean_pixels(ROWS, full)
    assert "isn't a single letter" in reject(ROWS, {**PAL, "kk": "#000"})
    assert "isn't a single letter" in reject(ROWS, {**PAL, ".": "#000"}) and "isn't a single letter" in reject(ROWS, {**PAL, " ": "#000"})
    assert "isn't a single letter" in reject(ROWS, {"k": "red", "y": "#fc3"}) and "isn't a single letter" in reject(ROWS, {"k": "#12345", "y": "#fc3"})
    assert "isn't a single letter" in reject(ROWS, {"k": 5, "y": "#fc3"}) and "isn't a single letter" in reject(ROWS, {5: "#000", "k": "#000", "y": "#fff"})
    assert "these letters aren't in your palette: q z" in reject(["kkzq"] * 4)
    assert reject(["...."] * 4) == "the picture is empty; put some colour in it"


def test_the_picture_is_crisp_svg_one_rect_per_run_and_passes_the_sanitiser():
    svg = art.pixel_svg(["kkyy", "....", "kyky", "yyyy"], {"k": "#000", "y": "#fc3"})
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300" width="400" height="300" shape-rendering="crispEdges">'
                          '<g transform="translate(50 0) scale(75)">') and svg.endswith("</rect></g></svg>".replace("</rect>", "/>"))
    assert '<g transform="translate(8 6) scale(12)">' in art.pixel_svg(["k" * 32] * 24, {"k": "#000"})
    assert '<g transform="translate(8 126) scale(12)">' in art.pixel_svg(["k" * 32] * 4, {"k": "#000"})
    assert svg.count("<rect") == 7 and '<rect x="0" y="0" width="2" height="1" fill="#000"/>' in svg
    assert '<rect x="2" y="0" width="2" height="1" fill="#fc3"/>' in svg and '<rect x="0" y="3" width="4" height="1" fill="#fc3"/>' in svg
    assert '<rect x="3" y="2" width="1" height="1" fill="#fc3"/>' in svg and 'y="1"' not in svg
    assert 'shape-rendering="crispEdges"' in art.sanitize_svg(svg) and art.render_png(art.sanitize_svg(svg))[:4] == b"\x89PNG"


# --- drawing them -----------------------------------------------------------------------------------------------------------
async def drawer(tmp_path, **kw):
    s, st, gm, agent = make(tmp_path, **kw)
    agent.tools.update({n: T.REGISTRY[n] for n in ("draw", "write_piece")})
    return s, st, agent


@pytest.mark.asyncio
async def test_pip_draws_in_pixels_and_the_grid_is_kept_with_the_picture(tmp_path):
    s, st, agent = await drawer(tmp_path, works_min_gap_minutes=0)
    r = await call(agent, "draw", title="A sun", pixels=ROWS, palette=PAL)
    assert "you finish a drawing, #1: A sun" in r.text and "looks in your workshop" not in r.text
    w = st.work(1)
    assert w["body"].startswith("<svg") and 'viewBox="0 0 400 300"' in w["body"]                  # stored as sanitised SVG, like any drawing
    assert st.pictures() == [{"id": 1, "title": "A sun", "subject": "", "rows": ROWS, "palette": {"k": "#2a1f1a", "y": "#fc3"}}]
    assert "letters aren't in your palette: z" in (await call(agent, "draw", title="Bad", pixels=["zzzz"] * 4, palette=PAL)).text
    assert "draw it as `pixels`" in (await call(agent, "draw", title="Nothing")).text and len(st.works()) == 1


@pytest.mark.asyncio
async def test_a_picture_of_a_creation_is_how_it_looks_and_a_redraw_replaces_the_grid(tmp_path):
    s, st, agent = await drawer(tmp_path)
    clock(st)
    assert "no creation called 'Moon Lamp'" in (await call(agent, "draw", title="x", pixels=ROWS, palette=PAL, of="Moon Lamp")).text
    r = await call(agent, "draw", title="My clock", pixels=ROWS, palette=PAL, of="gear clock")
    assert "It's how Gear Clock looks in your workshop now." in r.text and st.work(1)["subject"] == "Gear Clock"
    assert st.picture_of(subject="GEAR CLOCK") == {"rows": ROWS, "palette": {"k": "#2a1f1a", "y": "#fc3"}} and st.picture_of(subject="Moon Lamp") is None
    assert st.picture_of(title="my clock")["rows"] == ROWS and st.picture_of(title="Gear Clock") is None
    redo = ["kkkk"] * 4
    r = await call(agent, "draw", title="My clock, better", pixels=redo, palette=PAL, replaces=1)
    assert "redo #1" in r.text and "looks in your workshop" in r.text and st.picture_of(subject="Gear Clock")["rows"] == redo
    await call(agent, "draw", title="My clock, svg", svg='<svg><rect width="4" height="4"/></svg>', replaces=1)
    assert st.picture_of(subject="Gear Clock") is None and st.pictures() == []              # an SVG redraw has no grid
    assert st.work(1)["subject"] == "Gear Clock"


@pytest.mark.asyncio
async def test_the_nudges_are_facts_and_only_where_draw_is_a_tool(tmp_path):
    s, st, agent = await drawer(tmp_path)
    assert "draw makes a picture; a small pixel one is quick." in agent._free_time(time.time())
    st.log("arrived", place="library", label="the library", first_time=True)
    st.log("creation_made", id=1, name="Gear Clock", description="a clock", quality="sound", capabilities=[], quirks=[], project="clock")
    p = agent._perception("timer", [])
    assert "for the first time (draw can keep a picture of it)" in p and 'with of="Gear Clock", becomes how it looks' in p
    del agent.tools["draw"]
    p = agent._perception("timer", [])
    assert "draw can keep" not in p and "of=" not in p and "draw makes a picture" not in "\n".join(agent._free_time(time.time()))


@pytest.mark.asyncio
async def test_starting_a_project_mentions_sketching_it_when_draw_is_on(tmp_path):
    s, st, agent = await drawer(tmp_path)
    r = await call(agent, "start_project", name="Kite", goal="fly", steps=["frame", "cover"])
    assert "sketch it first with draw" not in r.text
    s.tools = ["draw"]
    r = await call(agent, "start_project", name="Boat", goal="float", steps=["hull", "sail"])
    assert r.text.endswith("You could sketch it first with draw.")


# --- in the world: the gallery-wall and stall-pictures modules (docs/DESIGN-modules.md, step 2) --------------------------------
async def rule_live(st, s, agent, name, now=None):
    from app import modules as M
    man, src = M.library(name)
    r = await M.propose(st, s, agent.runner, "world", man, src, now=now)
    await M.approve(st, s, agent.runner, r["id"], now=now)
    return st.module(r["id"])


@pytest.mark.asyncio
async def test_the_gallery_wall_hangs_the_latest_pictures_and_creations_wear_theirs(tmp_path):
    from app import modules as M
    s, st, agent = await drawer(tmp_path, works_per_day=20, works_min_gap_minutes=0, modules="on", module_runner="local")
    clock(st)
    st.add_work("drawing", "Old svg", "<svg/>")
    await call(agent, "draw", title="P0", pixels=ROWS, palette=PAL)
    await rule_live(st, s, agent, "gallery-wall")
    assert [o["key"] for o in WV.scene_view(st, s, None)["objects"]] == ["gallery-wall:drawing-2"]
    for i in range(1, 4):
        await call(agent, "draw", title=f"P{i}", pixels=ROWS, palette=PAL)
    await call(agent, "draw", title="Clock", pixels=["kkkk"] * 4, palette=PAL, of="Gear Clock")
    await M.step(st, s, agent.runner)                                                      # it hears of each new drawing
    d = WV.scene_view(st, s, None)
    assert len(st.pictures()) == 4 and len(st.pictures(10)) == 5
    objs = d["objects"]
    assert [o["key"] for o in objs] == ["gallery-wall:drawing-6", "gallery-wall:drawing-5", "gallery-wall:drawing-4"]
    assert objs[0]["rows"] == ["kkkk"] * 4 and objs[0]["frame"] and objs[0]["upright"] and objs[0]["tip"] == {"title": "Clock", "text": "One of Pip's drawings."}
    assert [o["pos"][:2] for o in objs] == [[-5.25, 2.3], [-7.15, 1.6], [-9.6, 1.5]]                 # the three spots on the back wall
    assert d["creations"][0]["picture"] == {"rows": ["kkkk"] * 4, "palette": {"k": "#2a1f1a", "y": "#fc3"}}
    assert WV.scene_view(st, s, None, "woods")["objects"] == []


@pytest.mark.asyncio
async def test_stall_pictures_show_copies_of_a_drawing_and_creations_pip_drew(tmp_path):
    from tests.test_stall import LOOT
    from app import modules as M
    s, st, agent = await drawer(tmp_path, works_min_gap_minutes=0, modules="on", module_runner="local")
    st.add_place("Brygdon", "brygdon", kind="market", status="real", created_at=time.time(), heard_at=time.time(), hours=[0, 24], daylight_only=0,
                 walk_minutes=10.0, loot=LOOT, verbs={"browse": ["see", None]}, description="A market by the quay.")
    await call(agent, "draw", title="The Marsh", pixels=ROWS, palette=PAL)
    st.add_work("drawing", "Svg one", "<svg/>")
    st.add_work("writing", "A poem", "words words")
    await call(agent, "draw", title="A poem", pixels=ROWS, palette=PAL)                           # a picture with the same title as the poem
    st.set_stall("Brygdon", "The Marsh", name="The Marsh", kind="work", qty=3, ask=4, attrs={"work": "drawing"})
    st.set_stall("Brygdon", "Svg one", name="Svg one", kind="work", qty=1, ask=4, attrs={"work": "drawing"})
    st.set_stall("Brygdon", "A poem", name="A poem", kind="work", qty=1, ask=3, attrs={"work": "writing"})
    st.set_stall("Brygdon", "carrots", name="carrots", kind="food", qty=2, ask=1, attrs={})
    clock(st)
    await call(agent, "draw", title="Clock face", pixels=["kkkk"] * 4, palette=PAL, of="Gear Clock")
    st.set_stall("Brygdon", "Gear Clock", name="Gear Clock", kind="creation", qty=1, ask=9, attrs={})
    st.set_stall("Brygdon", "Moon Lamp", name="Moon Lamp", kind="creation", qty=1, ask=9, attrs={})
    now = time.time()
    m = await rule_live(st, s, agent, "stall-pictures", now)
    assert m["due"] == now + 600
    d = WV.scene_view(st, s, None, "Brygdon")
    objs = {o["tip"]["title"]: o for o in d["objects"]}
    assert set(objs) == {"Gear Clock", "The Marsh"} and objs["The Marsh"]["frame"] and not objs["Gear Clock"]["frame"]
    assert objs["The Marsh"]["rows"] == ROWS and objs["The Marsh"]["tip"]["text"] == "3 on Pip's stall." and objs["Gear Clock"]["rows"] == ["kkkk"] * 4
    assert all(not o["upright"] and o["pos"][2] == -1.7 for o in d["objects"])                  # standing on Pip's stall
    assert {r["item"]: r for r in d["stall"]}["carrots"] == {"item": "carrots", "qty": 2, "ask": 1, "kind": "food"}
    st.db.execute("DELETE FROM stalls WHERE item = 'The Marsh'")
    st.db.commit()
    await M.step(st, s, agent.runner, now + 601)                                                   # it looks again
    assert [o["tip"]["title"] for o in WV.scene_view(st, s, None, "Brygdon")["objects"]] == ["Gear Clock"]
