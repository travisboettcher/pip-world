"""Projects: the pure rules (sanitising a plan, levels, the die, quality) and the helpers that read state."""
import random

import pytest

from app import projects as proj
from app.config import Settings
from app.state import State
from test_projects import FixedRng


def mk(tmp_path, **kw):
    kw.setdefault("sleep", False)
    return State(Settings(db_path=str(tmp_path / "p.db"), **kw))


def stage(name="s", minutes=60, progress=0.0, started=False, materials=None, **extra):
    return {"name": name, "minutes": minutes, "progress": progress, "started": started,
            "materials": materials or {}, **extra}


# --- sanitising --------------------------------------------------------------------------------
@pytest.mark.parametrize("value,expected", [(5, 5), ("7", 7), (7.9, 7), (-3, 1), (0, 1), (1, 1), (10, 10), (11, 10),
                                            (None, 4), ("abc", 4), ([], 4)])
def test_clamp_int(value, expected):
    assert proj.clamp_int(value, 1, 10, 4) == expected


def test_sanitize_abilities_keeps_known_distinct_names_in_order_at_most_two():
    assert proj.sanitize_abilities([" Patience ", "PRECISION", "patience", "ingenuity"]) == ["patience", "precision"]
    assert proj.sanitize_abilities(["bogus", "knowledge"]) == ["knowledge"]
    assert proj.sanitize_abilities(["precision"]) == ["precision"]


@pytest.mark.parametrize("raw", [None, "patience", [], ["bogus"], {"a": 1}, 5])
def test_sanitize_abilities_defaults_to_handiness(raw):
    out = proj.sanitize_abilities(raw)
    assert out == ["handiness"]
    out.append("x")
    assert proj.DEFAULT_ABILITIES == ["handiness"]                    # callers get their own copy


def test_sanitize_stages_names_minutes_and_defaults():
    out = proj.sanitize_stages(["  plain step  ", {"name": " cut " + "x" * 80}, {"name": "  "}, {"name": None}, {},
                                7, ["list"], {"name": "short", "minutes": 3}, {"name": "long", "minutes": "999"},
                                {"name": "mid", "minutes": "45"}], 10)
    assert [s["name"] for s in out] == ["plain step", "cut " + "x" * 56, "short", "long", "mid"]
    assert [s["minutes"] for s in out] == [60, 60, 15, 240, 45]
    assert all(s["guess"] == s["minutes"] and s["materials"] == {} and s["abilities"] == ["handiness"] for s in out)


def test_sanitize_stages_limit_counts_raw_entries_and_non_list_is_empty():
    raw = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
    assert [s["name"] for s in proj.sanitize_stages(raw, 2)] == ["a", "b"]
    assert proj.sanitize_stages(raw, 0) == []
    assert proj.sanitize_stages("abc", 5) == [] and proj.sanitize_stages(None, 5) == [] and proj.sanitize_stages({"name": "a"}, 5) == []
    assert [s["name"] for s in proj.sanitize_stages(["", "x", "y"], 2)] == ["x"]   # the cut is before dropping junk


def test_sanitize_stages_materials_are_normalised_and_capped_across_the_plan():
    out = proj.sanitize_stages([
        {"name": "one", "materials": {" Brass ": 3, "WOOD": "2", "zero": 0, "neg": -4, "": 2, "junk": "x"}},
        {"name": "two", "materials": {"brass": 3, "glue": 5}},
        {"name": "three", "materials": {"more": 1}},
    ], 5)
    assert out[0]["materials"] == {"brass": 3, "wood": 2}
    assert out[1]["materials"] == {"brass": 3}                                    # 8 units in total: brass fills it, glue gets 0
    assert out[2]["materials"] == {}
    assert sum(sum(s["materials"].values()) for s in out) == proj.MAX_MATERIAL_UNITS


def test_sanitize_stages_starting_units_reduce_the_budget_and_names_are_clipped():
    out = proj.sanitize_stages([{"name": "a", "materials": {"m" * 60: 5}}], 3, units=6)
    assert out[0]["materials"] == {"m" * 40: 2}
    assert proj.sanitize_stages([{"name": "a", "materials": {"x": 1}}], 3, units=8)[0]["materials"] == {}


def test_sanitize_stages_merges_names_that_normalise_alike_and_ignores_non_dict_materials():
    out = proj.sanitize_stages([{"name": "a", "materials": {"Rope": 1, "rope ": 2}},
                                {"name": "b", "materials": ["rope"]}, {"name": "c", "materials": None}], 3)
    assert out[0]["materials"] == {"rope": 3} and out[1]["materials"] == {} and out[2]["materials"] == {}


def test_sanitize_stages_keeps_abilities_the_step_names():
    out = proj.sanitize_stages([{"name": "a", "abilities": ["patience", "nope"]}], 3)
    assert out[0]["abilities"] == ["patience"]


def test_sanitize_strings_clips_skips_blanks_and_limits():
    assert proj.sanitize_strings(["a", " ", "", "b", "c", "d"], 3) == ["a", "b", "c"]
    assert proj.sanitize_strings(["x" * 300], 3) == ["x" * 160 + "..."]
    assert proj.sanitize_strings(["word " * 100], 3, 20) == ["word word word word..."]
    assert proj.sanitize_strings("abc", 3) == [] and proj.sanitize_strings(None, 3) == []
    assert proj.sanitize_strings([1, 2], 5) == ["1", "2"]
    assert proj.sanitize_strings(["a", "b"], 0) == []


def test_annotate_tags_abilities_and_may_correct_minutes_but_never_renames():
    steps = [{"name": "one", "minutes": 60, "guess": 60, "materials": {"m": 1}}, {"name": "two", "minutes": 30, "guess": 30}]
    out = proj.annotate(steps, [{"abilities": ["patience"], "minutes": 90, "name": "renamed"}, "junk"])
    assert out[0] == {"name": "one", "minutes": 90, "guess": 60, "materials": {"m": 1}, "abilities": ["patience"]}
    assert out[1] == {"name": "two", "minutes": 30, "guess": 30, "abilities": ["handiness"]}
    assert steps[0]["minutes"] == 60 and "abilities" not in steps[0]
    assert proj.annotate(steps, None)[0]["minutes"] == 60
    assert proj.annotate(steps, [{"minutes": 5000}, {"minutes": 1}])[0]["minutes"] == 240
    assert proj.annotate(steps, [{"minutes": 1}, {"minutes": "x"}])[0]["minutes"] == 15
    assert [s["minutes"] for s in proj.annotate(steps, [{"minutes": 120}])] == [120, 30]       # fewer notes than steps
    assert len(proj.annotate(steps, [{}, {}, {"abilities": ["precision"]}])) == 2               # more notes than steps
    assert proj.annotate([], [{}]) == []


def test_build_plan_review_fields_are_cleaned():
    steps = [{"name": "s", "minutes": 60, "guess": 60, "materials": {}, "abilities": ["handiness"]}]
    review = {"craft": "Clockmaking (gears)", "difficulty": 4, "tools": [" Needle File ", "", "x" * 60, "b", "c", "d"],
              "open_questions": ["q1", "q2", " ", "q3", "q4"], "hidden": ["h1", "h2", "h3", "h4", "h5"]}
    plan = proj.build_plan(steps, review)
    assert plan["craft"] == "clockmaking" and plan["difficulty"] == 4
    assert plan["tools"] == ["needle file", "x" * 40, "b"]
    assert plan["questions"] == ["q1", "q2", "q3"]
    assert plan["hidden"] == [{"fact": "h1", "found": False}, {"fact": "h2", "found": False}, {"fact": "h3", "found": False}]
    assert plan["stages"] == steps


def test_build_plan_hidden_facts_only_with_questions_and_longer_clip():
    steps = []
    assert proj.build_plan(steps, {"hidden": ["secret"]})["hidden"] == []
    plan = proj.build_plan(steps, {"open_questions": ["q" * 400], "hidden": ["h" * 400]})
    assert plan["hidden"][0]["fact"] == "h" * 240 + "..." and plan["questions"][0] == "q" * 160 + "..."


@pytest.mark.parametrize("raw,expected", [(0, 1), (1, 1), (3, 3), (5, 5), (6, 5), (None, 2), ("x", 2)])
def test_build_plan_difficulty_is_one_to_five_default_two(raw, expected):
    assert proj.build_plan([], {"difficulty": raw})["difficulty"] == expected


def test_build_plan_without_review_is_a_bare_plan():
    plan = proj.build_plan([], None)
    assert plan == {"craft": "tinkering", "difficulty": 2, "tools": [], "stages": [], "questions": [], "hidden": []}
    assert proj.build_plan([], {}) == plan


def test_new_stages_start_untouched_without_changing_the_plan():
    plan = {"stages": [{"name": "a", "minutes": 30, "materials": {"x": 1}}]}
    out = proj.new_stages(plan)
    assert out == [{"name": "a", "minutes": 30, "materials": {"x": 1}, "progress": 0.0, "started": False}]
    assert "progress" not in plan["stages"][0]


# --- progress ----------------------------------------------------------------------------------------
def test_current_stage_is_the_first_unfinished_one():
    p = {"stages": [stage(progress=60), stage(progress=10), stage()]}
    assert proj.current_stage(p) == 1
    assert proj.current_stage({"stages": [stage(progress=60), stage(progress=60)]}) is None
    assert proj.current_stage({"stages": []}) is None
    assert proj.current_stage({"stages": [stage(progress=60 - 1e-7)]}) is None           # float dust counts as done
    assert proj.current_stage({"stages": [stage(progress=60 - 1e-5)]}) == 0
    assert proj.current_stage({"stages": [stage(progress=0)]}) == 0


def test_crossroads_needs_an_active_project_with_nothing_to_do_and_questions_left():
    done = [stage(progress=60)]
    assert proj.crossroads({"status": "active", "stages": done, "questions": ["why?"]}) is True
    assert proj.crossroads({"status": "done", "stages": done, "questions": ["why?"]}) is False
    assert proj.crossroads({"status": "active", "stages": done, "questions": []}) is False
    assert proj.crossroads({"status": "active", "stages": [stage()], "questions": ["why?"]}) is False


def test_percent():
    assert proj.percent({"stages": [stage(minutes=100, progress=33)], "questions": []}) == 33
    assert proj.percent({"stages": [stage(minutes=100, progress=33.9)], "questions": []}) == 33          # truncated
    assert proj.percent({"stages": [stage(minutes=60, progress=60), stage(minutes=60, progress=0)], "questions": []}) == 50
    assert proj.percent({"stages": [stage(minutes=60, progress=90)], "questions": []}) == 100            # overshoot is capped per stage
    assert proj.percent({"stages": [stage(minutes=60, progress=90), stage(minutes=60)], "questions": []}) == 50
    assert proj.percent({"stages": [], "questions": []}) == 100
    assert proj.percent({"stages": [stage(minutes=60, progress=60)], "questions": ["open"]}) == 99
    assert proj.percent({"stages": [stage(minutes=100, progress=50)], "questions": ["open"]}) == 50
    assert proj.percent({"stages": [], "questions": ["open"]}) == 99


def test_upcoming_needs_sums_unstarted_stages_from_a_point():
    p = {"stages": [stage(materials={"a": 1}), stage(materials={"a": 2, "b": 1}, started=True),
                    stage(materials={"a": 4, "b": 2}), stage(materials={"a": 8})]}
    assert proj.upcoming_needs(p, 0) == {"a": 13, "b": 2}
    assert proj.upcoming_needs(p, 2) == {"a": 12, "b": 2}
    assert proj.upcoming_needs(p, 1) == {"a": 12, "b": 2}
    assert proj.upcoming_needs(p, 4) == {}


@pytest.mark.parametrize("xp,lvl", [(0, 0), (-10, 0), (59.9, 0), (60, 1), (239, 1), (240, 2), (539, 2), (540, 3),
                                    (959, 3), (960, 4), (1499, 4), (1500, 5), (10 ** 6, 5)])
def test_level_is_the_square_root_of_hours_capped_at_five(xp, lvl):
    assert proj.level(xp) == lvl


def test_stage_abilities_fall_back_to_a_fresh_default():
    assert proj.stage_abilities({"abilities": ["patience"]}) == ["patience"]
    d = proj.stage_abilities({})
    assert d == ["handiness"] and proj.stage_abilities({"abilities": []}) == ["handiness"]
    d.append("x")
    assert proj.DEFAULT_ABILITIES == ["handiness"]


def test_skill_for_blends_ability_levels_and_craft_familiarity(tmp_path):
    st = mk(tmp_path)
    st.add_ability_xp({"patience": 240, "precision": 60})                 # levels 2 and 1
    st.add_xp("clockmaking", 960)                                         # level 4
    p = {"craft": "clockmaking"}
    assert proj.skill_for(st, p, ["patience", "precision"]) == pytest.approx(1.5 + 0.5 * 4)
    assert proj.skill_for(st, p, ["patience"]) == pytest.approx(2 + 2)
    assert proj.skill_for(st, p, ["ingenuity"]) == pytest.approx(0 + 2)         # an ability with no practice counts as zero
    assert proj.skill_for(st, {"craft": "kites"}, ["precision"]) == pytest.approx(1.0)
    assert proj.skill_for(st, p, []) == pytest.approx(2.0)


def test_grant_xp_credits_the_craft_and_splits_minutes_between_abilities(tmp_path):
    st = mk(tmp_path)
    proj.grant_xp(st, {"craft": "kites"}, ["patience", "precision"], 40)
    assert st.skills() == {"kites": 40} and st.abilities() == {"patience": 20, "precision": 20}
    proj.grant_xp(st, {"craft": "kites"}, ["patience"], 10)
    assert st.skills() == {"kites": 50} and st.abilities()["patience"] == 30


# --- the die -------------------------------------------------------------------------------------------
class OneRoll(random.Random):
    def __init__(self, value):
        super().__init__(0)
        self.value = value

    def random(self):
        return self.value


def rolled(value, skill=0, tools=0, difficulty=1, energy=0.9):
    return proj.roll(OneRoll(value), skill, tools, difficulty, energy)


@pytest.mark.parametrize("value,expected", [(0.0, "setback"), (0.149, "setback"), (0.15, "slow"), (0.399, "slow"),
                                            (0.40, "good"), (0.899, "good"), (0.90, "breakthrough"), (0.999, "breakthrough")])
def test_roll_bands(value, expected):
    assert rolled(value) == expected


def test_roll_skill_adds_five_percent_a_level():
    assert rolled(0.06, skill=2) == "slow" and rolled(0.04, skill=2) == "setback"
    assert rolled(0.85, skill=2) == "breakthrough" and rolled(0.79, skill=2) == "good"
    assert rolled(0.13, skill=1.5) == "slow"            # fractional skill (abilities blend) counts, 0.05 * 1.5


def test_roll_each_tool_adds_five_percent_up_to_three():
    assert rolled(0.06, tools=2) == "slow" and rolled(0.04, tools=2) == "setback"
    assert rolled(0.76, tools=3) == "breakthrough" and rolled(0.74, tools=3) == "good"
    assert rolled(0.76, tools=9) == "breakthrough" and rolled(0.74, tools=9) == "good"       # the fourth tool adds nothing


def test_roll_difficulty_subtracts_five_percent_above_one():
    assert rolled(0.94, difficulty=1) == "breakthrough"
    assert rolled(0.94, difficulty=2) == "good" and rolled(0.96, difficulty=2) == "breakthrough"
    assert rolled(0.34, difficulty=5) == "setback" and rolled(0.36, difficulty=5) == "slow" and rolled(0.62, difficulty=5) == "good"
    assert rolled(0.34, difficulty=1) == "slow" and rolled(0.38, difficulty=5) == "slow"
    assert rolled(0.64, difficulty=5) == "good" and rolled(0.58, difficulty=5) == "slow"
    assert rolled(0.19, difficulty=2) == "setback" and rolled(0.21, difficulty=2) == "slow"
    assert rolled(0.36, difficulty=3) == "slow" and rolled(0.505, difficulty=3) == "good"


def test_roll_tiredness_costs_fifteen_percent_below_thirty_percent_energy():
    assert rolled(0.20, energy=0.3) == "slow" and rolled(0.20, energy=0.29) == "setback"
    assert rolled(0.20, energy=0.0) == "setback" and rolled(0.30, energy=0.29) == "slow"
    assert rolled(0.50, energy=0.29) == "slow" and rolled(0.54, energy=0.29) == "slow" and rolled(0.56, energy=0.29) == "good"


@pytest.mark.parametrize("rolled_,said,expected", [
    ("setback", "blowup", "blowup"), ("setback", "setback", "setback"), ("setback", "slow", "slow"),
    ("setback", "good", "slow"), ("setback", "breakthrough", "slow"),
    ("slow", "blowup", "setback"), ("slow", "setback", "setback"), ("slow", "slow", "slow"),
    ("slow", "good", "good"), ("slow", "breakthrough", "good"),
    ("good", "blowup", "slow"), ("good", "setback", "slow"), ("good", "slow", "slow"), ("good", "good", "good"),
    ("good", "breakthrough", "breakthrough"),
    ("breakthrough", "blowup", "good"), ("breakthrough", "setback", "good"), ("breakthrough", "slow", "good"),
    ("breakthrough", "good", "good"), ("breakthrough", "breakthrough", "breakthrough"),
])
def test_the_die_bounds_the_gms_verdict_to_one_step(rolled_, said, expected):
    assert proj.clamp_verdict(rolled_, said) == expected


@pytest.mark.parametrize("said", [None, "", "great", 3, ["good"]])
def test_an_unusable_verdict_leaves_the_roll(said):
    assert proj.clamp_verdict("slow", said) == "slow"


def history(*results):
    return {"history": [{"result": r, "text": f"{r} text"} for r in results]}


@pytest.mark.parametrize("results,skill,expected", [
    ([], 0, "sound"), ([], 2, "sound"), ([], 3, "fine"), ([], 5, "fine"), ([], 6, "masterwork"),
    (["setback"], 0, "rough"), (["setback"], 1, "rough"), (["setback"], 2, "sound"),
    (["breakthrough"], 0, "sound"), (["breakthrough"], 1, "fine"), (["breakthrough"], 2, "fine"),
    (["breakthrough", "breakthrough"], 0, "fine"), (["breakthrough", "breakthrough"], 1, "fine"),
    (["breakthrough"] * 3, 0, "masterwork"), (["breakthrough"] * 2, 2, "masterwork"),
    (["breakthrough", "setback"], 0, "sound"), (["setback", "setback"], 4, "sound"),
    (["good", "slow", "blowup"], 3, "fine"), (["good", "slow", "blowup"], 2, "sound"),
])
def test_quality_by_points(results, skill, expected):
    assert proj.quality(history(*results), skill) == expected


def test_scars_are_the_setback_texts_that_say_something():
    p = {"history": [{"result": "setback", "text": "snapped the wire"}, {"result": "good", "text": "fine"},
                     {"result": "setback", "text": ""}, {"result": "setback"}, {"result": "blowup", "text": "boom"}]}
    assert proj.scars(p) == ["snapped the wire"]


# --- helpers over state ---------------------------------------------------------------------------------
def test_missing_materials_reports_shortfalls_with_what_you_have(tmp_path):
    st = mk(tmp_path)
    st.add_item("brass wire", 3, "material")
    st.add_item("file", 1, "tool")
    st.add_item("apple", 5, "food")
    take, problems = proj.missing_materials(st, {"materials": {"brass wire": 3, "file": 1}})
    assert [(i["name"], q) for i, q in take] == [("brass wire", 3), ("file", 1)] and problems == []
    take, problems = proj.missing_materials(st, {"materials": {"brass wire": 4, "glue": 2, "apple": 1}})
    assert take == []
    assert problems == ["4 brass wire (you have 3)", "2 glue (you have 0)", "1 apple (you have 0)"]
    take, problems = proj.missing_materials(st, {"materials": {}})
    assert take == [] and problems == []


def test_mentioned_materials_are_owned_materials_the_stage_name_spells_out(tmp_path):
    st = mk(tmp_path)
    for name, kind in (("pendulum", "material"), ("gear", "material"), ("pendulum rod", "material"), ("file", "tool"),
                       ("spring", "material"), ("apple", "food")):
        st.add_item(name, 1, kind)
    got = proj.mentioned_materials(st, {"name": "Hang the Pendulum and the gears", "materials": {"gear": 1}})
    assert [i["name"] for i in got] == ["pendulum"]                 # gear is listed; 'pendulum rod' is not all in the name
    got = proj.mentioned_materials(st, {"name": "make the file and apple", "materials": {}})
    assert got == []                                                  # tools and food are never built in
    got = proj.mentioned_materials(st, {"name": "oil the springs", "materials": {}})
    assert [i["name"] for i in got] == ["spring"]                    # plurals match
    assert proj.mentioned_materials(st, {"name": "pendulums", "materials": {"Pendulum": 1}}) == []
    assert proj.mentioned_materials(st, {"name": "rependulumize", "materials": {}}) == []   # whole words only


def test_tools_owned_counts_distinct_tools_the_project_lists(tmp_path):
    st = mk(tmp_path)
    st.add_item("needle file", 1, "tool")
    st.add_item("brass wire", 1, "material")
    p = {"tools": ["needle file", "tweezers", "brass wire"]}
    assert proj.tools_owned(st, p) == 1
    assert proj.tools_owned(st, {"tools": []}) == 0
    st.add_item("tweezers", 1, "tool")
    assert proj.tools_owned(st, p) == 2


def test_fallback_narration_names_the_stage_for_every_result():
    texts = {r: proj.fallback_narration("the gears", r) for r in proj.VERDICTS}
    assert texts == {
        "blowup": "It went badly wrong on the gears, and you lost ground.",
        "setback": "Something went wrong on the gears, and you'll have to redo part of it.",
        "slow": "Work on the gears was slow and fiddly, but it moved forward.",
        "good": "You made steady progress on the gears.",
        "breakthrough": "Something clicked on the gears, and it came together faster than expected."}


def test_expectation_fields_only_include_what_was_predicted():
    c = {"expected": "well", "phrase": "you expected well", "error": -2, "surprise": "worse"}
    s = {"phrase": "you guessed 30", "surprise": "longer"}
    assert proj._expectation_fields(None, None) == {}
    assert proj._expectation_fields(c, None) == {"expected": "well", "expectation": "you expected well", "error": -2,
                                                "surprise": "worse"}
    assert proj._expectation_fields(None, s) == {"step_note": "you guessed 30", "step_surprise": "longer"}
    assert set(proj._expectation_fields(c, s)) == {"expected", "expectation", "error", "surprise", "step_note", "step_surprise"}


def test_feel_describes_growth_in_words_not_numbers(tmp_path):
    st = mk(tmp_path)
    assert proj.feel(st) == []
    st.add_ability_xp({"precision": 60, "patience": 240, "ingenuity": 10, "knowledge": 1500})   # 1, 2, 0, 5
    st.add_xp("clockmaking", 60)
    st.add_xp("kites", 540)
    st.add_xp("boats", 5)
    out = proj.feel(st)
    grown = out[0]
    assert grown.startswith("How you've grown: ")
    parts = grown[len("How you've grown: "):].split("; ")
    assert parts == ["learned (knowledge)", "patient (patience)", "a little careful (precision)"]
    assert out[1] == "Your experience: skilled at kites, getting the hang of clockmaking"
    assert len(out) == 2


def test_feel_ignores_unknown_abilities_and_covers_the_top_of_each_scale(tmp_path):
    st = mk(tmp_path)
    st.add_ability_xp({"mystery": 5000, "handiness": 1500})
    st.add_xp("masonry", 1500)
    st.add_xp("carving", 960)
    out = proj.feel(st)
    assert out == ["How you've grown: a true craftsman (handiness)",
                   "Your experience: a master of masonry, very good at carving"]
