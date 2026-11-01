"""The kind registry for invented places (place_kinds.py)."""
from app import place_kinds as K
from app.world import KINDS


def test_the_registry_has_the_four_kinds_with_their_rules():
    assert list(K.KINDS) == ["wild", "yard", "shop", "sight"]
    wild, yard, shop, sight = (K.KINDS[k] for k in ("wild", "yard", "shop", "sight"))
    assert set(wild.verbs) == {"gather"} and wild.loot_kinds == ("material", "food", "seed") and wild.max_tools == 0
    assert set(yard.verbs) == {"gather", "browse"} and "tool" in yard.loot_kinds and yard.max_tools == 1
    assert set(shop.verbs) == {"browse", "gather"} and set(shop.loot_kinds) == set(KINDS) and shop.max_tools == 2
    assert sight.verbs == {} and sight.loot_kinds == () and sight.words == ()
    assert (wild.capacity, wild.refill) == (120, 15) and (yard.capacity, yard.refill) == (120, 15)
    assert (shop.capacity, shop.refill) == (40, 2) and shop.session == (15, 30) and wild.session == (15, 60)
    assert shop.shop_hours and not wild.shop_hours and not sight.shop_hours
    assert all(set(k.loot_kinds) <= set(KINDS) for k in K.KINDS.values())


def test_guess_picks_the_kind_whose_words_appear_and_falls_back_to_a_sight():
    assert K.guess("an ironmonger with a drawer of odds and ends") == "shop"
    assert K.guess("the old quarry, full of scrap") == "yard"
    assert K.guess("a shingle beach where the gulls nest") == "wild"
    assert K.guess("a lake with a lovely view") == "sight"
    assert K.guess("") == "sight"


def test_check_keeps_a_proposed_kind_only_if_the_words_back_it():
    assert K.check("shop", "the ironmonger in Saltholm") == "shop"
    assert K.check("shop", "a quiet lake") == "sight"                 # nobody said there was a shop
    assert K.check("yard", "a lake, and a scrap heap behind the boathouse") == "yard"
    assert K.check("sight", "an ironmonger") == "sight"               # a sight needs no words
    assert K.check("castle", "a beach") == "wild"                     # unknown kind: guessed from the words
    assert K.check(None, "a lake") == "sight"


def test_shop_hours_are_bounded_and_other_kinds_keep_to_daylight():
    assert K.hours_for("shop") == (9, 17) and K.hours_for("wild") is None and K.hours_for("sight") is None
    assert K.hours_for("shop", 7, 19) == (7, 19)
    assert K.hours_for("shop", 3, 23) == (7, 19)                      # clamped into 7-10 / 16-19
    assert K.hours_for("shop", 10, 16) == (10, 16)                    # exactly six hours is allowed
    assert K.hours_for("shop", "x", None) == (9, 17)
    assert K.hours_for("shop", 10.6, 16.2) == (10, 16)


def test_gm_lines_list_every_kind_and_what_it_is_for():
    line = K.gm_lines()
    assert all(f"{k} (" in line for k in K.KINDS) and K.KINDS["sight"].help in line


def test_a_proposed_kind_is_kept_when_the_words_back_it_even_if_another_comes_first():
    assert K.check("shop", "a shop by the shore") == "shop"                 # the guess would be wild (shore)
    assert K.check(["shop"], "a shop by the shore") == "wild"                # not a kind name at all: the guess


def test_the_kinds_for_the_gm_exactly():
    assert K.gm_lines() == "; ".join(f"{k.name} ({k.help})" for k in K.KINDS.values())
    assert K.gm_lines().startswith("wild (somewhere outdoors to forage: a wood, a shore, a marsh edge); yard (")
