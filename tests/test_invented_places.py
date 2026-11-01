"""Places that characters mention become real (DESIGN-invented-places.md)."""
import sqlite3

from app.config import Settings
from app.state import State


def fresh(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"))
    return s, State(s)


# --- the places table ---------------------------------------------------------------------------
def test_a_place_row_round_trips_its_lists_and_maps(tmp_path):
    s, st = fresh(tmp_path)
    st.add_place("Saltholm", "saltholm", aliases=["saltholm ironmonger"], walk_minutes=30.0, hours=[9, 17],
                 mentions=[{"by": "Briar", "there": "an ironmonger"}], created_at=100.0, heard_at=100.0)
    row = st.place_row("saltholm")                                          # keys match without case
    assert row["key"] == "Saltholm" and row["core"] == "saltholm" and row["status"] == "heard"
    assert row["aliases"] == ["saltholm ironmonger"] and row["hours"] == [9, 17] and row["walk_minutes"] == 30.0
    assert row["mentions"] == [{"by": "Briar", "there": "an ironmonger"}] and row["loot"] == [] and row["verbs"] == {}
    assert row["on_account"] == {} and row["grown"] == 0 and row["real_at"] is None and row["kind"] == "sight"
    st.update_place("Saltholm", status="real", loot=[["brass wire", "material", 9, [1, 2], "wire", {}]], on_account={"brass wire": 2})
    row = st.place_row("Saltholm")
    assert row["status"] == "real" and row["loot"][0][0] == "brass wire" and row["on_account"] == {"brass wire": 2}
    assert [r["key"] for r in st.place_rows()] == ["Saltholm"] and st.place_row("Nowhere") is None


def test_an_older_database_gains_the_places_table(tmp_path):
    s, st = fresh(tmp_path)
    st.db.execute("DROP TABLE places")
    st.db.commit()
    st.db.close()
    st = State(s)
    assert st.place_rows() == []
