"""Tools: how tools are registered, offered and described."""
import struct

import pytest

from app import tools as T
from app.config import Settings
from app.llm.base import ToolSpec
from test_mut_tools_core import make, run, clock  # noqa: F401


@pytest.fixture
def scratch_registry():
    before_reg, before_scopes = dict(T.REGISTRY), dict(T.SCOPES)
    yield
    T.REGISTRY.clear(); T.REGISTRY.update(before_reg)
    T.SCOPES.clear(); T.SCOPES.update(before_scopes)


async def test_tool_registers_a_spec_a_scope_and_a_guarded_handler(tmp_path, clock, scratch_registry):
    ctx, st = make(tmp_path)
    seen = []

    async def handler(c, args):
        seen.append((c, args))
        return T.ToolResult("done")

    params = T._obj({"x": {"type": "string"}}, ["x"])
    assert T.tool("tmp_a", "does a thing", params, where="home")(handler) is handler       # the function is returned as it was
    spec, guarded = T.REGISTRY["tmp_a"]
    assert spec == ToolSpec("tmp_a", "does a thing", params) and T.SCOPES["tmp_a"] == ("home",)
    assert guarded is not handler
    r = await guarded(ctx, {"x": "1"})
    assert r.text == "done" and seen == [(ctx, {"x": "1"})]
    st.update_agent(location="library")
    r = await guarded(ctx, {"x": "2"})
    assert r.text == "you're at the library; go_to home first" and r.followup is True and len(seen) == 1


def test_tool_scope_defaults_to_anywhere_and_takes_a_tuple_or_a_name(scratch_registry):
    async def h(c, a):
        return T.ToolResult("")
    T.tool("tmp_b", "d", {})(h)
    T.tool("tmp_c", "d", {}, where=("woods", "junkyard"))(h)
    T.tool("tmp_d", "d", {}, where="library")(h)
    assert T.SCOPES["tmp_b"] == ("anywhere",) and T.SCOPES["tmp_c"] == ("woods", "junkyard") and T.SCOPES["tmp_d"] == ("library",)
    assert T.ANYWHERE == "anywhere"


def test_obj_builds_an_object_schema():
    assert T._obj({"a": {"type": "string"}}, ["a"]) == {"type": "object", "properties": {"a": {"type": "string"}},
                                                         "required": ["a"]}
    assert T._obj({}, []) == {"type": "object", "properties": {}, "required": []}


def test_the_shipped_tools_have_object_schemas_and_descriptions():
    for name, (spec, _) in T.REGISTRY.items():
        assert spec.name == name and spec.description and spec.parameters["type"] == "object"
        assert set(spec.parameters["required"]) <= set(spec.parameters["properties"])


# --- stages ----------------------------------------------------------------------------------------
def test_describe_stage_summarises_a_step():
    p = {"stages": [{"name": "cut", "minutes": 45, "materials": {"brass wire": 2, "glue": 1}, "started": False},
                    {"name": "fit", "minutes": 30, "materials": {}, "started": False},
                    {"name": "paint", "minutes": 20, "materials": {"paint": 1}, "started": True}]}
    assert T.describe_stage(p, 0) == "stage 1/3 'cut' (about 45 min of work; uses 2 brass wire, 1 glue)"
    assert T.describe_stage(p, 1) == "stage 2/3 'fit' (about 30 min of work)"
    assert T.describe_stage(p, 2) == "stage 3/3 'paint' (about 20 min of work)"            # already paid for


def test_picture_renders_the_drawing_at_the_look_width():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300"><rect width="400" height="300" fill="red"/></svg>'
    (mime, data), = T._picture({"body": svg})
    assert mime == "image/png" and data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert width == T.LOOK_WIDTH == 480 and height == 360


# --- which tools exist ------------------------------------------------------------------------------------
def settings(tmp_path, **kw):
    kw.setdefault("library_path", str(tmp_path / "nolibrary"))
    return Settings(db_path=str(tmp_path / "t.db"), **kw)


def test_enabled_tools_resolves_names_and_drops_what_cannot_work(tmp_path):
    s = settings(tmp_path, tools=["say", "eat", "say", "browse_library", "web_search", "sleep", "send_postcard", "read"],
                 sleep=False, tavily_api_key="", outreach="on", outreach_channels=[])
    out = T.enabled_tools(s)
    assert list(out) == ["say", "eat", "browse"]               # no key, no sleep, no way out; read is the reading module's
    assert out["say"] is T.REGISTRY["say"]


def test_enabled_tools_includes_optional_ones_when_their_condition_holds(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "metadata.db").write_text("")
    s = settings(tmp_path, tools=["web_search", "sleep", "send_postcard", "browse_library", "read"], sleep=True,
                 tavily_api_key="k", outreach="on", outreach_channels=["matrix"], library_path=str(tmp_path / "lib"))
    assert list(T.enabled_tools(s)) == ["web_search", "sleep", "send_postcard", "browse"]


@pytest.mark.parametrize("kw", [dict(outreach="off", outreach_channels=["matrix"]), dict(outreach="on", outreach_channels=[]),
                                dict(outreach="log", outreach_channels=[])])
def test_the_postcard_needs_outreach_and_a_channel(tmp_path, kw):
    assert T.enabled_tools(settings(tmp_path, tools=["send_postcard"], **kw)) == {}
    ok = settings(tmp_path, tools=["send_postcard"], outreach="log", outreach_channels=["matrix"])
    assert list(T.enabled_tools(ok)) == ["send_postcard"]


def test_a_tool_name_the_engine_doesnt_have_is_skipped_with_a_warning(tmp_path, caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="app.tools"):
        got = T.enabled_tools(settings(tmp_path, tools=["say", "plant", "teleport"]))      # plant: the garden module's, since 0.35.0
    assert list(got) == ["say"]
    assert [r.getMessage() for r in caplog.records] == [
        f"TOOLS names {n!r}, which isn't one of the engine's tools; skipped (a module may offer it)" for n in ("plant", "teleport")]


def test_enabled_tools_for_a_plain_setup_keeps_everything_asked_for(tmp_path):
    s = settings(tmp_path, tools=["set_activity", "eat", "rest", "note_to_self"])
    assert list(T.enabled_tools(s)) == ["set_activity", "eat", "rest", "note_to_self"]
    assert T.enabled_tools(settings(tmp_path, tools=[])) == {}
