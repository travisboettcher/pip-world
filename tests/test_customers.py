"""Customers at Pip's stall as a module (0.26.0): what a module can read about the stall, the `sell` effect the referee allows (only Pip's
own goods, at Pip's own ask, while Pip is there and the market is open), and the shipped `stall-customers` rule that replaces the engine's."""
import random

import pytest

from app import market as MK
from app import modules as M
from tests.test_stall import HOUR, LOOT, NOW, market, stocked
from tests.test_modules import live, rule


def mod(tmp_path, **kw):
    s, st, agent, ask = stocked(tmp_path, **kw)
    s.modules, s.module_runner, s.module_library = "on", "local", "on"
    return s, st, agent, ask


# --- reads -------------------------------------------------------------------------------------------------------------------
def test_a_module_reads_the_stall_its_prices_and_whether_pip_is_selling(tmp_path):
    s, st, agent, ask = mod(tmp_path, qty=5)
    m = live(st, rule(reads=["stalls", "pip"]), "x")
    ctx = M.context(st, s, m, NOW)
    fair = MK.fair_price(st, "Brygdon", "tomatoes", "food", {"food_value": 0.5}, NOW)
    assert ctx["stalls"] == [{"place": "Brygdon", "item": "tomatoes", "kind": "food", "qty": 5, "ask": ask, "fair": fair, "sold_today": 0, "selling": True}]
    assert ctx["pip"]["walking"] is False
    st.update_agent(location="workshop")
    assert M.context(st, s, m, NOW)["stalls"][0]["selling"] is False
    st.update_agent(location="Brygdon")
    st.start_session(0, 0, 10, NOW + 99999, kind="walk", target="Saltholm")
    ctx = M.context(st, s, m, NOW)
    assert ctx["stalls"][0]["selling"] is False and ctx["pip"]["walking"] is True


def test_where_pip_is_selling(tmp_path):
    s, st, agent, ask = mod(tmp_path)
    assert MK.selling_at(st, s, NOW) == "Brygdon"
    st.update_agent(activity="sleeping")
    assert MK.selling_at(st, s, NOW) is None
    st.update_agent(activity="idle", location="Saltholm")
    assert MK.selling_at(st, s, NOW) is None                                                  # a shop: no stall
    st.update_agent(location="Brygdon")
    st.update_place("Brygdon", hours=[0, 1])
    assert MK.selling_at(st, s, NOW) is None                                                  # shut
    st.update_agent(location="nowhere-at-all")
    assert MK.selling_at(st, s, NOW) is None


# --- the sell effect ---------------------------------------------------------------------------------------------------------
def test_sell_takes_pips_goods_at_pips_ask_and_logs_the_sale(tmp_path):
    s, st, agent, ask = mod(tmp_path, qty=5)
    m = live(st, rule(proposes=["sell"]), "x")
    coins = st.coins()
    M.apply(st, m, M.plan(st, m, {"sell": [{"place": "Brygdon", "item": "Tomatoes", "qty": 2}]}, NOW, "on_tick", s), NOW)
    assert st.coins() == coins + 2 * ask and st.stall_rows("Brygdon")[0]["qty"] == 3 and st.stall_rows("Brygdon")[0]["sold_today"] == 2
    sale = next(e["data"] for e in st.events(5) if e["kind"] == "stall_sale")
    assert {k: sale[k] for k in ("place", "item", "qty", "coins", "left")} == {"place": "Brygdon", "item": "tomatoes", "qty": 2, "coins": 2 * ask, "left": 3}
    assert M._budget(st.module(m["id"]), NOW)["sell"] == 1
    M.apply(st, m, M.plan(st, m, {"sell": [{"place": "Brygdon", "item": "tomatoes", "qty": 3}]}, NOW, "on_tick", s), NOW)
    assert st.stall_rows("Brygdon") == []


def test_sell_is_refused_unless_pip_is_there_selling_and_the_goods_are_on_the_stall(tmp_path):
    s, st, agent, ask = mod(tmp_path, qty=30)
    m = live(st, rule(proposes=["sell"]), "x")
    def why(result):
        with pytest.raises(M.Refused) as e:
            M.plan(st, m, result, NOW, "on_tick", s)
        return str(e.value)
    assert why({"sell": [{"place": "Brygdon", "item": "awl", "qty": 1}]}) == "there is no awl on Pip's stall at Brygdon"
    assert why({"sell": [{"place": "Brygdon", "item": "tomatoes", "qty": 0}]}) == "`sell` qty is 1 to 8 (what is on the stall, and what the market takes today)"
    assert why({"sell": [{"place": "Brygdon", "item": "tomatoes", "qty": 9}]}).startswith("`sell` qty is 1 to 8")
    assert why({"sell": [{"place": "Brygdon", "item": "tomatoes", "qty": True}]}).startswith("`sell` qty is 1 to")
    assert why({"sell": {"place": "Brygdon"}}) == "`sell` is a list of {place, item, qty}"
    assert why({"sell": [{"place": "Brygdon"}]}) == "`sell` is a list of {place, item, qty}"
    assert why({"sell": [{"place": "Brygdon", "item": "tomatoes", "qty": 1}] * 4}) == "`sell` is a list of {place, item, qty}"
    with pytest.raises(M.Refused) as e:
        M.plan(st, m, {"sell": [{"place": "Brygdon", "item": "tomatoes", "qty": 1}]}, NOW, "on_tick")
    assert str(e.value) == "Pip isn't selling at Brygdon right now"                         # no settings: can't tell, so no
    st.update_agent(location="workshop")
    assert why({"sell": [{"place": "Brygdon", "item": "tomatoes", "qty": 1}]}) == "Pip isn't selling at Brygdon right now"
    st.update_agent(location="Brygdon")
    M.apply(st, m, M.plan(st, m, {"sell": [{"place": "Brygdon", "item": "tomatoes", "qty": 6}]}, NOW, "on_tick", s), NOW)
    assert why({"sell": [{"place": "Brygdon", "item": "tomatoes", "qty": 3}]}).startswith("`sell` qty is 1 to 2")
    st.update_module(m["id"], budget={"day": M._day(NOW), "sell": M.PER_DAY["sell"]})
    m = st.module(m["id"])
    assert why({"sell": [{"place": "Brygdon", "item": "tomatoes", "qty": 1}]}) == f"it has used today's {M.PER_DAY['sell']} `sell`"
    assert "sell" not in M.PIP_PROPOSES and "sell" in M.PROPOSES


def test_a_creation_on_the_stall_goes_to_its_buyer(tmp_path):
    s, st, agent = market(tmp_path)
    s.modules = "on"
    from tests.test_world_view import clock
    c = clock(st)
    st.set_stall("Brygdon", "gear clock", name="Gear Clock", kind="creation", qty=1, ask=9, attrs={"creation_id": c["id"]})
    m = live(st, rule(proposes=["sell"]), "x")
    M.apply(st, m, M.plan(st, m, {"sell": [{"place": "Brygdon", "item": "gear clock", "qty": 1}]}, NOW, "on_tick", s), NOW)
    assert not st.creations() and st.stall_rows("Brygdon") == []


# --- the shipped rule --------------------------------------------------------------------------------------------------------
async def customers(tmp_path, **kw):
    s, st, agent, ask = mod(tmp_path, **kw)
    man, src = M.library("stall-customers")
    r = await M.propose(st, s, M.LocalRunner(), M.SHIPPED, man, src, man["reason"], now=NOW)
    m = st.module(r["id"])
    assert m["status"] == "live" and m["report"]["clean"], m["report"]
    return s, st, agent, ask, m


@pytest.mark.asyncio
async def test_customers_stop_at_about_the_engines_rate(tmp_path):
    s, st, agent, ask, m = await customers(tmp_path, qty=200)
    await M.step(st, s, None, NOW)                                                            # the first look only starts the clock
    assert not [e for e in st.events(5) if e["kind"] == "stall_sale"]
    sold = 0
    for h in range(1, 41):
        await M.step(st, s, None, NOW + h * HOUR / 4)
    sold = sum(e["data"]["qty"] for e in st.events(200) if e["kind"] == "stall_sale")
    assert 8 <= sold <= 8 * 2                                                                 # ~2 an hour for 10 hours, at most 8 a day
    assert st.stall_rows("Brygdon")[0]["sold_today"] == sold


@pytest.mark.asyncio
async def test_nobody_stops_while_pip_is_away_or_at_a_silly_price(tmp_path):
    s, st, agent, ask, m = await customers(tmp_path, qty=50)
    await M.step(st, s, None, NOW)
    st.update_agent(location="workshop")
    for h in range(1, 20):
        await M.step(st, s, None, NOW + h * HOUR)
    st.update_agent(location="Brygdon")
    st.db.execute("UPDATE stalls SET ask = ?", (ask * 3,))
    st.db.commit()
    for h in range(20, 40):
        await M.step(st, s, None, NOW + h * HOUR)
    assert not [e for e in st.events(200) if e["kind"] == "stall_sale"] and st.module(m["id"])["fails"] == 0


def test_the_engines_own_modules_get_their_own_call_allowance(tmp_path):
    from tests.test_modules import modular
    s, st, agent = modular(tmp_path)
    m = live(st, rule(), "def on_tick(ctx):\n    return {}\n", author=M.SHIPPED)
    st.update_module(m["id"], budget={"day": M._day(NOW), "calls": M.PER_DAY["calls"]})
    import asyncio
    r = asyncio.run(M.call(st, s, M.LocalRunner(), st.module(m["id"]), "on_tick", NOW))
    assert r["ok"] and not r["refused"]


def test_three_lines_can_sell_at_once(tmp_path):
    s, st, agent, ask = mod(tmp_path, qty=9)
    st.add_item("awl", 3, "tool", "")
    st.add_item("brass wire", 3, "material", "")
    for name, kind in (("awl", "tool"), ("brass wire", "material")):
        MK.list_on_stall(st, "Brygdon", name, 3, MK.fair_price(st, "Brygdon", name, kind, {}, NOW), NOW)
    m = live(st, rule(proposes=["sell"]), "x")
    lines = [{"place": "Brygdon", "item": n, "qty": 1} for n in ("tomatoes", "awl", "brass wire")]
    M.apply(st, m, M.plan(st, m, {"sell": lines}, NOW, "on_tick", s), NOW)
    assert sorted(r["qty"] for r in st.stall_rows("Brygdon")) == [2, 2, 8]


# --- the rule's own logic (module_library/stall-customers.py), called directly ---------------------------------------------------
def customers_module():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("stall_customers", Path(MK.__file__).parent / "module_library" / "stall-customers.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = customers_module()


def line(**kw):
    return {"place": "Brygdon", "item": "tomatoes", "kind": "food", "qty": 200, "ask": 10, "fair": 10, "sold_today": 0, "selling": True, **kw}


def tick(rows, last, now, seed=1):
    return C.on_tick({"now": now, "state": {} if last is None else {"at": last}, "stalls": rows, "seed": seed, "pip": {}})


@pytest.mark.parametrize("ratio, factor", [(0.0, 1.25), (0.85, 1.25), (1.0, 1.0), (1.3, 0.5), (1.6, 0.0), (2.0, 0.0)])
def test_the_dearer_the_ask_the_fewer_stop(ratio, factor):
    assert C.factor(ratio) == pytest.approx(factor)
    assert C.factor(ratio) == MK.stall_factor(ratio)                                             # the same curve the stall quotes


def test_a_poisson_count_has_the_right_mean():
    rng = random.Random(1)
    for mu in (0.3, 1.0, 4.0):
        draws = [C.poisson(rng, mu) for _ in range(20000)]
        assert min(draws) >= 0 and sum(draws) / len(draws) == pytest.approx(mu, rel=0.05)
    assert C.poisson(rng, 0) == 0 and C.poisson(rng, -1) == 0


def test_the_first_look_only_starts_the_clock_and_an_hour_at_most_is_credited():
    assert tick([line()], None, NOW) == {"state": {"at": NOW}}
    one = [sum(s["qty"] for s in tick([line()], NOW - HOUR, NOW, seed).get("sell", [])) for seed in range(300)]
    ten = [sum(s["qty"] for s in tick([line()], NOW - 10 * HOUR, NOW, seed).get("sell", [])) for seed in range(300)]
    assert sum(one) == sum(ten) and sum(one) / 300 == pytest.approx(C.DEMAND_PER_HOUR, rel=0.15)


def test_only_lines_selling_now_and_within_the_days_take_and_the_stock_sell():
    rows = [line(item="away", selling=False), line(item="full", sold_today=8), line(item="few", qty=1), line(item="fine")]
    got = {s["item"]: s["qty"] for seed in range(50) for s in tick(rows, NOW - HOUR, NOW, seed).get("sell", [])}
    assert set(got) <= {"few", "fine"} and got.get("few", 1) == 1
    capped = [s["qty"] for seed in range(200) for s in tick([line(sold_today=7)], NOW - HOUR, NOW, seed).get("sell", [])]
    assert capped and max(capped) == 1                                                            # one more today at most
    assert all("sell" not in tick([line(ask=30)], NOW - HOUR, NOW, seed) for seed in range(100))  # a silly price: nobody
    cheap = sum(sum(s["qty"] for s in tick([line(ask=5)], NOW - HOUR, NOW, seed).get("sell", [])) for seed in range(300))
    fair = sum(sum(s["qty"] for s in tick([line()], NOW - HOUR, NOW, seed).get("sell", [])) for seed in range(300))
    assert cheap > fair
