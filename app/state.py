"""SQLite-backed world state: agent stats, event log, inbox, memories, usage."""
import json
import logging
import re
import sqlite3
import threading
import time
from datetime import date

from .config import Settings
from . import firsts as firstsmod
from .memory import RECALL_EVENT_KINDS, event_importance, STOP_WORDS, recall_text
from .text import craft_name
from .world import KINDS, STARTER_ITEMS, normalize_attrs

log = logging.getLogger("state")

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  hunger REAL NOT NULL, energy REAL NOT NULL,
  mood TEXT NOT NULL, location TEXT NOT NULL, activity TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  hunger_alerted INTEGER NOT NULL DEFAULT 0,
  energy_alerted INTEGER NOT NULL DEFAULT 0,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  kind TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  text TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0,
  sender TEXT NOT NULL DEFAULT 'A visitor', gift INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, text TEXT NOT NULL,
  section TEXT NOT NULL DEFAULT 'diary',
  status TEXT NOT NULL DEFAULT 'open',
  outcome TEXT NOT NULL DEFAULT '',
  edited_at REAL,
  kind TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  description TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'tool',
  qty INTEGER NOT NULL DEFAULT 1, attrs TEXT NOT NULL DEFAULT '{}', ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS garden (
  plot INTEGER PRIMARY KEY, seed TEXT NOT NULL, crop TEXT NOT NULL,
  planted_at REAL NOT NULL, ready_at REAL NOT NULL, yield INTEGER NOT NULL,
  food_value REAL NOT NULL, notified INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, goal TEXT NOT NULL DEFAULT '',
  craft TEXT NOT NULL, difficulty INTEGER NOT NULL,
  stages TEXT NOT NULL, tools TEXT NOT NULL DEFAULT '[]', history TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'active', outcome TEXT NOT NULL DEFAULT '',
  ts REAL NOT NULL, finished_at REAL
);
CREATE TABLE IF NOT EXISTS work_session (
  id INTEGER PRIMARY KEY CHECK (id = 1), project_id INTEGER NOT NULL, stage INTEGER NOT NULL,
  minutes REAL NOT NULL, started_at REAL NOT NULL, ends_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS creations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
  project_id INTEGER, quality TEXT NOT NULL, spec TEXT NOT NULL, runtime TEXT NOT NULL DEFAULT '{}', ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS characters (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, kind TEXT NOT NULL, creation_id INTEGER,
  persona TEXT NOT NULL, chatter_minutes REAL NOT NULL, next_chatter_at REAL NOT NULL,
  heard TEXT NOT NULL DEFAULT '[]', replies TEXT NOT NULL DEFAULT '[]', ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS letters (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, sender TEXT NOT NULL, recipient TEXT NOT NULL,
  text TEXT NOT NULL, enclosed TEXT NOT NULL DEFAULT '', parcel TEXT, deliver_at REAL NOT NULL,
  delivered_at REAL, attempts INTEGER NOT NULL DEFAULT 0, reply_to INTEGER
);
CREATE TABLE IF NOT EXISTS bookmarks (
  book_id INTEGER PRIMARY KEY, title TEXT NOT NULL, section INTEGER NOT NULL DEFAULT 0,
  offset INTEGER NOT NULL DEFAULT 0, percent INTEGER NOT NULL DEFAULT 0, sessions INTEGER NOT NULL DEFAULT 0,
  finished INTEGER NOT NULL DEFAULT 0, unreadable INTEGER NOT NULL DEFAULT 0, last_read REAL
);
CREATE TABLE IF NOT EXISTS skills (craft TEXT PRIMARY KEY COLLATE NOCASE, xp REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS night_decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, op TEXT NOT NULL, target_kind TEXT NOT NULL DEFAULT '',
  target_id INTEGER, args TEXT NOT NULL DEFAULT '{}', before TEXT NOT NULL DEFAULT '{}', reason TEXT NOT NULL DEFAULT '',
  cites TEXT NOT NULL DEFAULT '[]', summary TEXT NOT NULL DEFAULT '', applied INTEGER NOT NULL DEFAULT 0,
  undone INTEGER NOT NULL DEFAULT 0, shown INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS focus (
  id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, text TEXT NOT NULL, ref_kind TEXT NOT NULL DEFAULT '',
  ref_id INTEGER, status TEXT NOT NULL DEFAULT 'open', decided_at REAL NOT NULL, reviewed_at REAL,
  note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS capability_snapshots (day TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS turning_points (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, period_start REAL NOT NULL, period_end REAL NOT NULL,
  score INTEGER NOT NULL, signals TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS expectations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, kind TEXT NOT NULL, project_id INTEGER, craft TEXT NOT NULL DEFAULT '',
  subject TEXT NOT NULL DEFAULT '', expected TEXT NOT NULL, actual TEXT NOT NULL, error REAL NOT NULL,
  surprising INTEGER NOT NULL DEFAULT 0, direction TEXT, event_id INTEGER
);
CREATE TABLE IF NOT EXISTS day_stats (day TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS works (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
  body TEXT NOT NULL, caption TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS modules (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, kind TEXT NOT NULL, author TEXT NOT NULL, api INTEGER NOT NULL,
  subject TEXT NOT NULL DEFAULT '', manifest TEXT NOT NULL, source TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, replaces INTEGER, state TEXT NOT NULL DEFAULT '{}',
  offers TEXT NOT NULL DEFAULT '[]', facts TEXT NOT NULL DEFAULT '{}', lines TEXT NOT NULL DEFAULT '[]', due REAL, cursor INTEGER NOT NULL DEFAULT 0,
  report TEXT NOT NULL DEFAULT '{}', note TEXT NOT NULL DEFAULT '', fails INTEGER NOT NULL DEFAULT 0, budget TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL, decided_at REAL
);
CREATE TABLE IF NOT EXISTS module_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, module_id INTEGER NOT NULL, ts REAL NOT NULL, hook TEXT NOT NULL, ok INTEGER NOT NULL,
  ms INTEGER NOT NULL, summary TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS module_calls_by_module ON module_calls (module_id, id);
CREATE TABLE IF NOT EXISTS outreach (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, kind TEXT NOT NULL, channel TEXT NOT NULL,
  conversation TEXT NOT NULL DEFAULT '', text TEXT NOT NULL, status TEXT NOT NULL, error TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS place_finds (
  place TEXT NOT NULL, item TEXT NOT NULL, times INTEGER NOT NULL DEFAULT 0, last_ts REAL NOT NULL,
  PRIMARY KEY (place, item)
);
CREATE TABLE IF NOT EXISTS places (
  key TEXT PRIMARY KEY COLLATE NOCASE, core TEXT NOT NULL, aliases TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'heard', kind TEXT NOT NULL DEFAULT 'sight', distance TEXT NOT NULL DEFAULT 'far',
  blurb TEXT NOT NULL DEFAULT '', walk_minutes REAL, hours TEXT NOT NULL DEFAULT 'null',
  daylight_only INTEGER NOT NULL DEFAULT 1, verbs TEXT NOT NULL DEFAULT '{}', loot TEXT NOT NULL DEFAULT '[]',
  mentions TEXT NOT NULL DEFAULT '[]', description TEXT NOT NULL DEFAULT '', on_account TEXT NOT NULL DEFAULT '{}',
  grown INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, heard_at REAL NOT NULL, real_at REAL,
  source TEXT NOT NULL DEFAULT 'mention'
);
CREATE TABLE IF NOT EXISTS map_places (
  key TEXT PRIMARY KEY COLLATE NOCASE, x REAL NOT NULL, y REAL NOT NULL, placed_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reflection_cites (
  reflection_id INTEGER NOT NULL, ref_kind TEXT NOT NULL, ref_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS reflection_cites_by_reflection ON reflection_cites (reflection_id);
CREATE TABLE IF NOT EXISTS purses (party TEXT PRIMARY KEY, coins INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS market_prices (   -- how far one booth's price for one item has drifted (see market.py)
  place TEXT NOT NULL, item TEXT NOT NULL, local REAL NOT NULL, local_at REAL NOT NULL, day TEXT NOT NULL DEFAULT '',
  sold_today INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (place, item)
);
CREATE TABLE IF NOT EXISTS stalls (   -- Pip's own stall at a market (see market.py)
  place TEXT NOT NULL, item TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', attrs TEXT NOT NULL DEFAULT '{}',
  qty INTEGER NOT NULL, ask INTEGER NOT NULL, sold INTEGER NOT NULL DEFAULT 0, earned INTEGER NOT NULL DEFAULT 0,
  sold_today INTEGER NOT NULL DEFAULT 0, day TEXT NOT NULL DEFAULT '', PRIMARY KEY (place, item)
);
CREATE TABLE IF NOT EXISTS tills (place TEXT PRIMARY KEY, coins INTEGER NOT NULL, day TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS happenings (     -- small events from the world (see happenings.py)
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, slot TEXT NOT NULL, category TEXT NOT NULL, tone TEXT NOT NULL,
  severity TEXT NOT NULL, lens TEXT NOT NULL, seed TEXT NOT NULL, context TEXT NOT NULL DEFAULT '{}', effects TEXT NOT NULL DEFAULT '[]',
  effects_line TEXT NOT NULL DEFAULT '', meaning TEXT NOT NULL DEFAULT '{}', read_as TEXT NOT NULL DEFAULT '', text TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '', author TEXT NOT NULL DEFAULT 'template', status TEXT NOT NULL DEFAULT 'applied',
  ticks_seen INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS happening_rolls (slot TEXT PRIMARY KEY, ts REAL NOT NULL, roll REAL NOT NULL, hit INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS facets (
  key TEXT PRIMARY KEY, label TEXT NOT NULL, tier TEXT NOT NULL, first_event_id INTEGER,
  first_ts REAL NOT NULL, last_ts REAL NOT NULL, count INTEGER NOT NULL DEFAULT 1, shown INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS abilities (name TEXT PRIMARY KEY, xp REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS emotions (name TEXT PRIMARY KEY, value REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS emotion_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, emotion TEXT NOT NULL, delta REAL NOT NULL, value REAL NOT NULL,
  cause TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS reflections (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
  importance INTEGER NOT NULL DEFAULT 5, period_start REAL NOT NULL, period_end REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS people (
  name TEXT PRIMARY KEY COLLATE NOCASE, notes TEXT NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS recall_index USING fts5(text, source UNINDEXED, ref UNINDEXED, ts UNINDEXED);
CREATE TABLE IF NOT EXISTS memory_context (
  source TEXT NOT NULL, ref TEXT NOT NULL, ts REAL NOT NULL, place TEXT, people TEXT NOT NULL DEFAULT '[]', activity TEXT,
  mood TEXT, feeling TEXT, project TEXT, importance INTEGER NOT NULL DEFAULT 3, uses TEXT NOT NULL DEFAULT '[]',
  shown_at REAL NOT NULL DEFAULT 0, shown_with TEXT NOT NULL DEFAULT '[]', faded INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (source, ref)
);
CREATE TABLE IF NOT EXISTS usage (
  day TEXT PRIMARY KEY, input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0, calls INTEGER NOT NULL DEFAULT 0
);
"""

STAT_FIELDS = ("hunger", "energy", "mood", "location", "activity")
NOTE_IMPORTANCE = {"diary": 4, "learned": 4, "ambitions": 4}  # other notes: 3
USES_KEPT = 20                                                  # uses of a memory kept for its activation (reminders.py)
RECALL_INDEX_VERSION = "2"  # bump to rebuild the recall index from stored data on the next start
SECTIONS = ("diary", "todo", "wishlist", "ambitions", "learned")
RESOLVABLE = ("todo", "wishlist", "ambitions")  # sections whose items can be crossed off
EDITABLE = tuple(sec for sec in SECTIONS if sec != "diary")  # the diary is a record: never rewritten


def clean_sender(name) -> str:
    return " ".join(str(name or "").split())[:40] or "A visitor"


FIRSTS_VERSION = "6"
RETURN_GAP_HOURS = 36  # a facet seen again after this long counts as a return  # bump to rebuild facets from the log when firsts.py changes
SHOWINGS_DONE = 99  # backfilled history is never presented as new


def clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("oes") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def name_key(name: str) -> str:
    """What makes two item names the same thing: case and plurals don't ('Tomatoes' = 'tomato')."""
    return " ".join(_singular(w) for w in str(name).lower().split())


class State:
    def __init__(self, settings: Settings, path: str | None = None):
        self.s = settings
        self.lock = threading.RLock()
        self.listeners: list = []   # callables(kind, data, ts) run after each logged event; they must not break logging
        self.db = sqlite3.connect(path or settings.db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.executescript(SCHEMA)
            # DBs created before a column existed
            for table, col, ddl in (
                ("agent", "description", "TEXT NOT NULL DEFAULT ''"),
                ("memories", "section", "TEXT NOT NULL DEFAULT 'diary'"),
                ("memories", "status", "TEXT NOT NULL DEFAULT 'open'"),
                ("memories", "outcome", "TEXT NOT NULL DEFAULT ''"),
                ("memories", "kind", "TEXT NOT NULL DEFAULT ''"),
                ("memories", "edited_at", "REAL"),
                ("inbox", "sender", "TEXT NOT NULL DEFAULT 'A visitor'"),
                ("inbox", "gift", "INTEGER NOT NULL DEFAULT 0"),
                ("characters", "about", "TEXT NOT NULL DEFAULT ''"),
                ("characters", "life", "TEXT NOT NULL DEFAULT '[]'"),
                ("creations", "given_to", "TEXT"),
                ("inbox", "offers", "INTEGER NOT NULL DEFAULT 0"),             # times it was held back for another look (unanswered)
                ("inbox", "source", "TEXT NOT NULL DEFAULT 'web'"),           # 'web' or the channel it came through
                ("inbox", "conversation", "TEXT NOT NULL DEFAULT ''"),        # the channel's thread reference
                ("inbox", "external_id", "TEXT NOT NULL DEFAULT ''"),         # the channel's message id (replay guard)
                ("works", "revisions", "INTEGER NOT NULL DEFAULT 0"),           # times Pip redrew it after looking
                ("events", "importance", "INTEGER NOT NULL DEFAULT 0"),
                ("reflections", "grounded", "INTEGER NOT NULL DEFAULT 1"),     # 0 = a hunch: nothing cited / unsupported
                ("reflections", "support", "TEXT NOT NULL DEFAULT 'legacy'"),  # supported|partly|unsupported|unchecked|none|legacy
                ("projects", "questions", "TEXT NOT NULL DEFAULT '[]'"),   # open questions (strings)
                ("projects", "hidden", "TEXT NOT NULL DEFAULT '[]'"),      # [{fact, found}], unseen until discovered
                ("projects", "findings", "TEXT NOT NULL DEFAULT '[]'"),    # what Pip has learned (strings)
                ("projects", "dry", "INTEGER NOT NULL DEFAULT 0"),         # dry experiments in a row
                ("projects", "revised_at", "INTEGER NOT NULL DEFAULT 0"),  # len(history) at the last plan revision
                ("work_session", "expect", "TEXT NOT NULL DEFAULT ''"),     # what Pip said it expects (may be empty)
                ("work_session", "kind", "TEXT NOT NULL DEFAULT 'work'"),   # work | walk | read
                ("work_session", "target", "TEXT NOT NULL DEFAULT ''"),     # walk: place; read: book title
                ("characters", "told", "TEXT NOT NULL DEFAULT '[]'"),      # what a neighbor has told Pip (phrases)
                ("characters", "upcoming", "TEXT NOT NULL DEFAULT '[]'"),  # a neighbor's plans: [{what, due_at}]
                ("letters", "gist", "TEXT NOT NULL DEFAULT ''"),           # the sender's one-line summary of it
                ("characters", "place", "TEXT NOT NULL DEFAULT ''"),       # a resident's place (its key)
                ("characters", "wares", "TEXT NOT NULL DEFAULT '[]'"),
                ("characters", "look", "TEXT NOT NULL DEFAULT '{}'"),
                ("works", "pixels", "TEXT NOT NULL DEFAULT ''"),          # a pixel picture: {"rows": [...], "palette": {...}} (art.py)
                ("works", "subject", "TEXT NOT NULL DEFAULT ''"),         # the creation a picture is of: then it is how that creation looks      # how they are drawn in the world view (looks.py)     # what they sell: [{name, kind, description, per_day, weight, attrs}]
            ):
                if col not in {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            if not self.db.execute("SELECT 1 FROM agent").fetchone():
                self.db.execute(
                    "INSERT INTO agent (id, hunger, energy, mood, location, activity, updated_at) "
                    "VALUES (1, 0.2, 0.9, 'curious', 'workshop', 'idle', ?)",
                    (time.time(),),
                )
            self._normalize_crafts()
            self._seed_abilities()
            self._backfill_firsts()
            self._backfill_portraits()
            if self.meta("recall_indexed") != RECALL_INDEX_VERSION:
                self._backfill_recall()
            if self.meta("memory_context") != "1":
                self._backfill_memory_context()
            self.merge_duplicate_items()
            if not self.db.execute("SELECT 1 FROM meta WHERE key = 'starter_items'").fetchone():
                for it in STARTER_ITEMS:  # once ever, so used-up seeds don't come back on restart
                    self.add_item(it["name"], it["qty"], it["kind"], it["description"], it["attrs"])
                self.db.execute("INSERT INTO meta VALUES ('starter_items', '1')")
            self.db.commit()

    # --- agent stats -------------------------------------------------
    def agent(self) -> dict:
        with self.lock:
            return dict(self.db.execute("SELECT * FROM agent WHERE id = 1").fetchone())

    def update_agent(self, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self.lock:
            self.db.execute(f"UPDATE agent SET {cols} WHERE id = 1", tuple(fields.values()))
            self.db.commit()

    def apply_decay(self, now: float | None = None) -> list[str]:
        """Advance stats by elapsed time. Returns names of newly crossed alerts."""
        now = now or time.time()
        with self.lock:
            a = self.agent()
            hours = max(0.0, now - a["updated_at"]) / 3600
            energy_rate = (
                self.s.sleep_recover_per_hour if a["activity"] == "sleeping"
                else self.s.recover_per_hour if a["activity"] == "resting" else -self.s.energy_per_hour
            )
            sess = self.session()
            if sess and sess["kind"] in ("work", "experiment", "gather"):
                energy_rate -= self.s.work_energy_per_hour
            hunger_rate = self.s.hunger_per_hour * (0.5 if a["activity"] == "sleeping" else 1)
            hunger = clamp(a["hunger"] + hunger_rate * hours)
            energy = clamp(a["energy"] + energy_rate * hours)
            new = []
            h_alert = hunger >= self.s.hunger_alert
            e_alert = energy <= self.s.energy_alert
            if h_alert and not a["hunger_alerted"]:
                new.append("hunger")
            if e_alert and not a["energy_alerted"]:
                new.append("energy")
            self.update_agent(
                hunger=hunger, energy=energy, updated_at=now,
                hunger_alerted=int(h_alert), energy_alerted=int(e_alert),
            )
            return new

    # --- events ------------------------------------------------------
    def log(self, kind: str, **data) -> int:
        now = time.time()
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO events (ts, kind, data) VALUES (?, ?, ?)",
                (now, kind, json.dumps(data)),
            )
            new, back = self._note_facets(kind, data, now, cur.lastrowid)
            extra = {**({"firsts": new} if new else {}), **({"returns": back} if back else {})}
            self.db.execute("UPDATE events SET data = ?, importance = ? WHERE id = ?",
                            (json.dumps({**data, **extra}),
                             event_importance(kind, data, new), cur.lastrowid))
            if kind in RECALL_EVENT_KINDS and (text := recall_text(kind, data)):
                self._index(f"event:{kind}", cur.lastrowid, now, text, commit=False, data=data,
                            importance=event_importance(kind, data, new))
            self.db.commit()
        for fn in list(self.listeners):
            try:
                fn(kind, data, now)
            except Exception:
                log.exception("event listener failed")
        return cur.lastrowid

    # --- emotions (see emotions.py) ---------------------------------------------------
    def emotion_rows(self) -> dict[str, tuple[float, float]]:
        with self.lock:
            return {r["name"]: (r["value"], r["updated_at"]) for r in self.db.execute("SELECT * FROM emotions")}

    def set_emotion(self, name: str, value: float, ts: float) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO emotions VALUES (?, ?, ?)", (name, value, ts))
            self.db.commit()

    def add_emotion_log(self, ts: float, emotion: str, delta: float, value: float, cause: str) -> None:
        with self.lock:
            self.db.execute("INSERT INTO emotion_log (ts, emotion, delta, value, cause) VALUES (?, ?, ?, ?, ?)",
                            (ts, emotion, delta, value, cause))
            self.db.commit()

    def emotion_log(self, limit: int = 100, since: float | None = None) -> list[dict]:
        q, args = "SELECT * FROM emotion_log", []
        if since is not None:
            q += " WHERE ts >= ?"
            args.append(since)
        with self.lock:
            rows = self.db.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]

    # --- firsts (see firsts.py, DESIGN-self.md) -------------------------------------
    def _note_facets(self, kind: str, data: dict, ts: float, event_id: int,
                     shown: int = 0) -> tuple[list[dict], list[dict]]:
        """Count this event's facets. Returns (firsts, returns): facets seen for the first time ({key, label, tier}),
        and facets seen again after a long gap ({key, label, days})."""
        new, back = [], []
        for key, label, tier in firstsmod.facets(kind, data, self.s, ts):
            row = self.db.execute("SELECT last_ts, label FROM facets WHERE key = ?", (key,)).fetchone()
            if row:
                gap = (ts - row["last_ts"]) / 86400
                if gap * 24 >= RETURN_GAP_HOURS and not key.startswith("period:") and row["label"].startswith("the first time "):
                    back.append({"key": key, "label": row["label"], "days": round(gap, 1)})
                self.db.execute("UPDATE facets SET count = count + 1, last_ts = ? WHERE key = ?", (ts, key))
            else:
                self.db.execute("INSERT INTO facets (key, label, tier, first_event_id, first_ts, last_ts, shown) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?)", (key, label, tier, event_id, ts, ts, shown))
                new.append({"key": key, "label": label, "tier": tier})
        return new, back

    def _backfill_firsts(self) -> None:
        """One-time: replay the existing log so history gets its true first dates (silently: nothing is 'new')."""
        if self.meta("firsts_v") == FIRSTS_VERSION:
            return
        self.db.execute("DELETE FROM facets")
        for row in self.db.execute("SELECT id, ts, kind, data FROM events ORDER BY id").fetchall():
            data = {k: v for k, v in json.loads(row["data"]).items() if k not in ("firsts", "returns")}
            new, back = self._note_facets(row["kind"], data, row["ts"], row["id"], shown=SHOWINGS_DONE)
            extra = {**({"firsts": new} if new else {}), **({"returns": back} if back else {})}
            self.db.execute("UPDATE events SET data = ?, importance = ? WHERE id = ?",
                            (json.dumps({**data, **extra}),
                             event_importance(row["kind"], data, new), row["id"]))
        self.set_meta(firsts_v=FIRSTS_VERSION)

    def place_visits(self, place: str) -> dict | None:
        """How often Pip has arrived at a place, and when first and last (from its facet), or None if never."""
        with self.lock:
            row = self.db.execute("SELECT first_ts, last_ts, count FROM facets WHERE key = ?", (f"place:{place}",)).fetchone()
        return dict(row) if row else None

    def last_arrived(self, place: str) -> float | None:
        """When Pip last arrived at a place (from the facet count), or None if it never has."""
        with self.lock:
            row = self.db.execute("SELECT last_ts FROM facets WHERE key = ?", (f"place:{place}",)).fetchone()
        return row["last_ts"] if row else None

    def recent_firsts(self, max_age_hours: float, showings: int, limit: int, now: float | None = None) -> list[dict]:
        """Firsts young enough and not yet shown enough times; majors first, then newest."""
        now = now or time.time()
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM facets WHERE first_ts >= ? AND shown < ? "
                "ORDER BY (tier = 'major') DESC, first_ts DESC LIMIT ?",
                (now - max_age_hours * 3600, showings, limit)).fetchall()
        return [dict(r) for r in rows]

    def mark_firsts_shown(self, keys: list[str]) -> None:
        with self.lock:
            self.db.executemany("UPDATE facets SET shown = shown + 1 WHERE key = ?", [(k,) for k in keys])
            self.db.commit()

    def firsts_between(self, start: float, end: float, limit: int = 12) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM facets WHERE first_ts > ? AND first_ts <= ? "
                "ORDER BY (tier = 'major') DESC, first_ts LIMIT ?", (start, end, limit)).fetchall()
        return [dict(r) for r in rows]

    def events(self, limit: int = 50, before_id: int | None = None, after_id: int | None = None) -> list[dict]:
        """Newest first by default; with after_id, oldest first (for polling forward)."""
        q, args = "SELECT * FROM events", []
        if after_id is not None:
            q += " WHERE id > ? ORDER BY id ASC LIMIT ?"
            args += [after_id, limit]
        else:
            if before_id:
                q += " WHERE id < ?"
                args.append(before_id)
            q += " ORDER BY id DESC LIMIT ?"
            args.append(limit)
        with self.lock:
            rows = self.db.execute(q, args).fetchall()
        return [{**dict(r), "data": json.loads(r["data"])} for r in rows]

    def events_since(self, ts: float, limit: int = 2000) -> list[dict]:
        """Events newer than ts, oldest first."""
        with self.lock:
            rows = self.db.execute("SELECT * FROM events WHERE ts > ? ORDER BY id ASC LIMIT ?", (ts, limit)).fetchall()
        return [{**dict(r), "data": json.loads(r["data"])} for r in rows]

    # --- inbox -------------------------------------------------------
    def add_inbox(self, text: str, sender: str = "A visitor", gift: bool = False, source: str = "web",
                  conversation: str = "", external_id: str = "") -> int:
        sender = clean_sender(sender)
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO inbox (ts, text, sender, gift, source, conversation, external_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (time.time(), text, sender, int(gift), source, conversation, external_id))
            self.db.commit()
            return cur.lastrowid

    def reoffer_inbox(self, inbox_id: int) -> None:
        """Put a message Pip read but didn't answer back in the inbox once more."""
        with self.lock:
            self.db.execute("UPDATE inbox SET consumed = 0, offers = offers + 1 WHERE id = ?", (inbox_id,))
            self.db.commit()

    def inbox_has(self, source: str, external_id: str) -> bool:
        with self.lock:
            return bool(external_id) and self.db.execute(
                "SELECT 1 FROM inbox WHERE source = ? AND external_id = ?", (source, external_id)).fetchone() is not None

    def inbox_rows(self, ids: list[int]) -> list[dict]:
        if not ids:
            return []
        with self.lock:
            marks = ",".join("?" * len(ids))
            return [dict(r) for r in self.db.execute(f"SELECT * FROM inbox WHERE id IN ({marks}) ORDER BY id", ids)]

    def pending_inbox(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM inbox WHERE consumed = 0 ORDER BY id")]

    def consume_inbox(self, ids: list[int]) -> None:
        with self.lock:
            self.db.executemany("UPDATE inbox SET consumed = 1 WHERE id = ?", [(i,) for i in ids])
            self.db.commit()

    # --- memories (the journal) ----------------------------------------
    def add_memory(self, text: str, section: str = "diary", kind: str = "") -> int:
        """Write a note; a wish may have a `kind` (see wishes.py)."""
        if section not in SECTIONS:
            raise ValueError(f"unknown section {section!r}; options: {list(SECTIONS)}")
        with self.lock:
            now = time.time()
            cur = self.db.execute(
                "INSERT INTO memories (ts, text, section, kind) VALUES (?, ?, ?, ?)", (now, text, section, kind))
            self._index(f"note:{section}", cur.lastrowid, now, text, commit=False, importance=NOTE_IMPORTANCE.get(section, 3))
            self.db.commit()
            return cur.lastrowid

    def memories(self, section: str | None = None, status: str | None = None, limit: int = 10) -> list[dict]:
        """Newest `limit` entries matching the filters, returned oldest first.
        Archived entries (status 'archived') are hidden unless asked for explicitly."""
        q, args = "SELECT * FROM memories WHERE 1=1", []
        if status != "archived":
            q += " AND status != 'archived'"
        if section:
            q += " AND section = ?"
            args.append(section)
        if status:
            q += " AND status = ?"
            args.append(status)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self.lock:
            rows = self.db.execute(q, args).fetchall()
        return [dict(r) for r in reversed(rows)]

    def resolve_memory(self, memory_id: int, outcome: str = "") -> str:
        """Mark a wishlist/ambition item done. Returns an error string, or '' on success."""
        with self.lock:
            row = self.db.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
            if not row:
                return f"no note #{memory_id}"
            if row["section"] not in RESOLVABLE:
                return f"note #{memory_id} is in {row['section']}; only {'/'.join(RESOLVABLE)} items can be resolved"
            self.db.execute("UPDATE memories SET status = 'done', outcome = ? WHERE id = ?", (outcome, memory_id))
            self._index(f"note:{row['section']}", memory_id, row["ts"],
                        row["text"] + (f" (done: {outcome})" if outcome else " (done)"), commit=False)
            self.db.commit()
            return ""

    # --- items (belongings) ---------------------------------------------
    @staticmethod
    def _item(row) -> dict:
        return {**dict(row), "attrs": json.loads(row["attrs"])}

    def add_item(self, name: str, qty: int = 1, kind: str = "tool", description: str = "",
                 attrs: dict | None = None) -> dict:
        name = name.strip()[:60]
        if not name:
            raise ValueError("item needs a name")
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}; options: {list(KINDS)}")
        if qty < 1:
            raise ValueError("qty must be at least 1")
        with self.lock:
            row = next((r for r in self.db.execute("SELECT * FROM items ORDER BY id")
                        if name_key(r["name"]) == name_key(name)), None)
            if row:  # same item again: stack it
                self.db.execute("UPDATE items SET qty = qty + ?, description = COALESCE(NULLIF(?, ''), description) "
                                "WHERE id = ?", (qty, description[:200], row["id"]))
            else:
                self.db.execute(
                    "INSERT INTO items (name, description, kind, qty, attrs, ts) VALUES (?, ?, ?, ?, ?, ?)",
                    (name, description[:200], kind, qty, json.dumps(normalize_attrs(name, kind, attrs)), time.time()))
            self.db.commit()
            return self._item(self.db.execute("SELECT * FROM items WHERE name = ?", (row["name"] if row else name,)).fetchone())

    def merge_duplicate_items(self) -> int:
        """Fold stacks that differ only by case or plural into the oldest one. Returns how many stacks were folded away."""
        merged = 0
        with self.lock:
            keeper: dict[str, int] = {}
            for r in self.db.execute("SELECT * FROM items ORDER BY id").fetchall():
                k = (name_key(r["name"]), r["kind"])
                if k in keeper:
                    self.db.execute("UPDATE items SET qty = qty + ? WHERE id = ?", (r["qty"], keeper[k]))
                    self.db.execute("DELETE FROM items WHERE id = ?", (r["id"],))
                    merged += 1
                else:
                    keeper[k] = r["id"]
            self.db.commit()
        return merged

    def items(self) -> list[dict]:
        with self.lock:
            return [self._item(r) for r in self.db.execute("SELECT * FROM items ORDER BY id")]

    def find_item(self, query: str, kind: str | None = None) -> tuple[dict | None, str]:
        """Resolve a loose name ('needle file') to one item. Returns (item, '') or (None, error)."""
        q = str(query).strip().lower()
        rows = [i for i in self.items() if not kind or i["kind"] == kind]
        exact = [i for i in rows if name_key(i["name"]) == name_key(q)]
        if exact:
            return exact[0], ""
        part = [i for i in rows if q and (q in i["name"].lower() or i["name"].lower() in q)]
        if len(part) == 1:
            return part[0], ""
        if not part:
            return None, f"you don't have {query!r}" + (f" (kind: {kind})" if kind else "")
        return None, "which one? " + ", ".join(i["name"] for i in part)

    def take_item(self, item_id: int, qty: int = 1) -> None:
        with self.lock:
            self.db.execute("UPDATE items SET qty = qty - ? WHERE id = ?", (qty, item_id))
            self.db.execute("DELETE FROM items WHERE id = ? AND qty <= 0", (item_id,))
            self.db.commit()

    # --- coins and markets (see market.py) ------------------------------
    START_COINS = 10

    def coins(self, party: str = "pip") -> int:
        with self.lock:
            row = self.db.execute("SELECT coins FROM purses WHERE party = ?", (party,)).fetchone()
        return row["coins"] if row else (self.START_COINS if party == "pip" else 0)

    def add_coins(self, party: str, delta: int) -> int:
        """Change a purse by `delta` coins (a purse never goes below zero). Returns the new total."""
        with self.lock:
            total = self.coins(party) + int(delta)
            if total < 0:
                raise ValueError(f"{party} has only {self.coins(party)} coins")
            self.db.execute("INSERT INTO purses (party, coins) VALUES (?, ?) ON CONFLICT(party) DO UPDATE SET coins = excluded.coins",
                            (party, total))
            self.db.commit()
        return total

    def price_row(self, place: str, item: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM market_prices WHERE place = ? AND item = ?", (place, item)).fetchone()
        return dict(row) if row else None

    def set_price_row(self, place: str, item: str, local: float, local_at: float, day: str, sold_today: int) -> None:
        with self.lock:
            self.db.execute("INSERT INTO market_prices (place, item, local, local_at, day, sold_today) VALUES (?, ?, ?, ?, ?, ?) "
                            "ON CONFLICT(place, item) DO UPDATE SET local = excluded.local, local_at = excluded.local_at, "
                            "day = excluded.day, sold_today = excluded.sold_today",
                            (place, item, local, local_at, day, sold_today))
            self.db.commit()

    def stall_rows(self, place: str) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM stalls WHERE place = ? ORDER BY item", (place,)).fetchall()
        return [{**dict(r), "attrs": json.loads(r["attrs"])} for r in rows]

    def set_stall(self, place: str, item: str, **fields) -> None:
        """Create or change one line of a stall (`item` is the name key); a new line needs name, kind, qty and ask."""
        vals = {k: json.dumps(v) if k == "attrs" else v for k, v in fields.items()}
        with self.lock:
            if self.db.execute("SELECT 1 FROM stalls WHERE place = ? AND item = ?", (place, item)).fetchone():
                self.db.execute(f"UPDATE stalls SET {', '.join(f'{k} = ?' for k in vals)} WHERE place = ? AND item = ?", (*vals.values(), place, item))
            else:
                self.db.execute(f"INSERT INTO stalls (place, item, {', '.join(vals)}) VALUES (?, ?, {', '.join('?' for _ in vals)})", (place, item, *vals.values()))
            self.db.commit()

    def delete_stall(self, place: str, item: str) -> None:
        with self.lock:
            self.db.execute("DELETE FROM stalls WHERE place = ? AND item = ?", (place, item))
            self.db.commit()

    def till_row(self, place: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM tills WHERE place = ?", (place,)).fetchone()
        return dict(row) if row else None

    def set_till(self, place: str, coins: int, day: str) -> None:
        with self.lock:
            self.db.execute("INSERT INTO tills (place, coins, day) VALUES (?, ?, ?) "
                            "ON CONFLICT(place) DO UPDATE SET coins = excluded.coins, day = excluded.day", (place, int(coins), day))
            self.db.commit()

    # --- happenings (see happenings.py) ---------------------------------
    HAPPENING_JSON = ("context", "effects", "meaning")

    def _happening(self, row) -> dict:
        return {**dict(row), **{k: json.loads(row[k]) for k in self.HAPPENING_JSON}}

    def add_happening(self, **fields) -> dict:
        vals = {k: json.dumps(v) if k in self.HAPPENING_JSON else v for k, v in fields.items()}
        with self.lock:
            cur = self.db.execute(f"INSERT INTO happenings ({', '.join(vals)}) VALUES ({', '.join('?' for _ in vals)})", tuple(vals.values()))
            self.db.commit()
        return self.happening(cur.lastrowid)

    def happening(self, happening_id: int) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM happenings WHERE id = ?", (happening_id,)).fetchone()
        return self._happening(row) if row else None

    def happenings(self, limit: int = 20) -> list[dict]:
        """Newest first."""
        with self.lock:
            return [self._happening(r) for r in self.db.execute("SELECT * FROM happenings ORDER BY id DESC LIMIT ?", (limit,))]

    def update_happening(self, happening_id: int, **fields) -> None:
        vals = {k: json.dumps(v) if k in self.HAPPENING_JSON else v for k, v in fields.items()}
        with self.lock:
            self.db.execute(f"UPDATE happenings SET {', '.join(f'{k} = ?' for k in vals)} WHERE id = ?", (*vals.values(), happening_id))
            self.db.commit()

    def happening_roll(self, slot: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM happening_rolls WHERE slot = ?", (slot,)).fetchone()
        return dict(row) if row else None

    def add_happening_roll(self, slot: str, ts: float, roll: float, hit: bool) -> None:
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO happening_rolls (slot, ts, roll, hit) VALUES (?, ?, ?, ?)", (slot, ts, roll, int(hit)))
            self.db.commit()

    def scale_plot_time(self, plot: int, factor: float, now: float | None = None) -> None:
        """Make the time a growing plot has left `factor` times as long."""
        now = now or time.time()
        with self.lock:
            row = self.db.execute("SELECT ready_at FROM garden WHERE plot = ?", (plot,)).fetchone()
            if row:
                self.db.execute("UPDATE garden SET ready_at = ? WHERE plot = ?", (now + max(0.0, row["ready_at"] - now) * factor, plot))
                self.db.commit()

    def add_plot_yield(self, plot: int, delta: int) -> None:
        with self.lock:
            self.db.execute("UPDATE garden SET yield = MAX(1, yield + ?) WHERE plot = ?", (int(delta), plot))
            self.db.commit()

    # --- garden ----------------------------------------------------------
    def project_limit(self) -> int:
        """Projects Pip can keep going at once: the starting limit plus workshop it built, never above the cap."""
        return min(self.s.max_active_projects_cap, self.s.max_active_projects + int(self.meta("extra_project_slots") or 0))

    def add_project_slot(self) -> int | None:
        with self.lock:
            if self.project_limit() >= self.s.max_active_projects_cap:
                return None
            self.set_meta(extra_project_slots=int(self.meta("extra_project_slots") or 0) + 1)
            return self.project_limit()

    def plot_count(self) -> int:
        """Plots Pip has: the starting number plus any it cleared, never above the cap."""
        return min(self.s.garden_plots_max, self.s.garden_plots + int(self.meta("extra_plots") or 0))

    def add_plot(self) -> int | None:
        """One more plot, or None if the garden is as big as the world allows. Returns the new plot's number."""
        with self.lock:
            if self.plot_count() >= self.s.garden_plots_max:
                return None
            self.set_meta(extra_plots=int(self.meta("extra_plots") or 0) + 1)
            return self.plot_count()

    def garden(self, now: float | None = None) -> list[dict]:
        now = now or time.time()
        with self.lock:
            rows = {r["plot"]: dict(r) for r in self.db.execute("SELECT * FROM garden")}
        out = []
        for n in range(1, self.plot_count() + 1):
            r = rows.get(n)
            if not r:
                out.append({"plot": n, "state": "empty"})
            else:
                left = r["ready_at"] - now
                out.append({**r, "state": "ready" if left <= 0 else "growing",
                            "ready_in_min": max(0, int(left // 60) + (1 if left % 60 else 0))})
        return out

    def plant(self, plot: int, seed: str, crop: str, minutes: float, yield_: int, food_value: float) -> None:
        now = time.time()
        with self.lock:
            self.db.execute("INSERT INTO garden (plot, seed, crop, planted_at, ready_at, yield, food_value) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (plot, seed, crop, now, now + minutes * 60 / self.s.garden_speed, yield_, food_value))
            self.db.commit()

    def clear_plot(self, plot: int) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM garden WHERE plot = ?", (plot,)).fetchone()
            self.db.execute("DELETE FROM garden WHERE plot = ?", (plot,))
            self.db.commit()
            return dict(row) if row else None

    def garden_newly_ready(self) -> list[dict]:
        """Crops that ripened since we last looked (each is reported once)."""
        now = time.time()
        with self.lock:
            rows = [dict(r) for r in self.db.execute(
                "SELECT * FROM garden WHERE ready_at <= ? AND notified = 0", (now,))]
            self.db.execute("UPDATE garden SET notified = 1 WHERE ready_at <= ?", (now,))
            self.db.commit()
        return rows

    def edit_memory(self, memory_id: int, text: str) -> tuple[str, str]:
        """Rewrite an open non-diary note. Returns (error, previous_text); error is '' on success."""
        with self.lock:
            row = self.db.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
            if not row:
                return f"no note #{memory_id}", ""
            if row["section"] not in EDITABLE:
                return (f"note #{memory_id} is a {row['section']} entry, and those can't be changed - "
                        "write a new one if something has changed"), ""
            if row["status"] != "open":
                return f"note #{memory_id} is already {row['status']}", ""
            self.db.execute("UPDATE memories SET text = ?, edited_at = ? WHERE id = ?", (text, time.time(), memory_id))
            self._index(f"note:{row['section']}", memory_id, row["ts"], text, commit=False)
            self.db.commit()
            return "", row["text"]

    @staticmethod
    def related(a: str, b: str) -> bool:
        """Do two phrases share a meaningful word (4+ letters, plural-insensitive)?"""
        def words(t): return {w.removesuffix("s") for w in re.findall(r"[a-z]+", t.lower()) if len(w) >= 4}
        return bool(words(a) & words(b))

    def matching_wishes(self, item_name: str) -> list[dict]:
        """Open wishlist entries that share a meaningful word with an item (e.g. 'tiny needle file')."""
        return [m for m in self.memories("wishlist", status="open", limit=50) if self.related(item_name, m["text"])]

    # --- projects, work sessions, skills -------------------------------------
    PROJECT_JSON = ("stages", "tools", "history", "questions", "hidden", "findings")

    def _project(self, row) -> dict:
        return {**dict(row), **{k: json.loads(row[k]) for k in self.PROJECT_JSON}}

    def add_project(self, name: str, goal: str, craft: str, difficulty: int, stages: list[dict],
                    tools: list[str]) -> dict:
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO projects (name, goal, craft, difficulty, stages, tools, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, goal, craft, difficulty, json.dumps(stages), json.dumps(tools), time.time()))
            self.db.commit()
            return self.project(cur.lastrowid)

    def project(self, project_id: int) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return self._project(row) if row else None

    def projects(self, status: str | None = None, limit: int = 50) -> list[dict]:
        q, args = "SELECT * FROM projects", []
        if status:
            q += " WHERE status = ?"
            args.append(status)
        with self.lock:
            rows = self.db.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
        return [self._project(r) for r in reversed(rows)]

    def update_project(self, project_id: int, **fields) -> None:
        vals = {k: json.dumps(v) if k in self.PROJECT_JSON else v for k, v in fields.items()}
        with self.lock:
            self.db.execute(f"UPDATE projects SET {', '.join(f'{k} = ?' for k in vals)} WHERE id = ?",
                            (*vals.values(), project_id))
            self.db.commit()

    def find_project(self, query, status: str = "active") -> tuple[dict | None, str]:
        """Resolve '#3', 3 or a loose name ('clock') to one project with the given status."""
        rows = self.projects(status)
        q = str(query).strip().lower().lstrip("#")
        if q.isdigit():
            hit = [p for p in rows if p["id"] == int(q)]
            return (hit[0], "") if hit else (None, f"no {status} project #{q}")
        exact = [p for p in rows if p["name"].lower() == q]
        part = exact or [p for p in rows if q and (q in p["name"].lower() or p["name"].lower() in q)]
        if len(part) == 1:
            return part[0], ""
        if not part:
            names = ", ".join(f"#{p['id']} {p['name']}" for p in rows) or "none"
            return None, f"no {status} project called {query!r} (yours: {names})"
        return None, "which one? " + ", ".join(f"#{p['id']} {p['name']}" for p in part)

    def session(self) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM work_session WHERE id = 1").fetchone()
        return dict(row) if row else None

    def start_session(self, project_id: int, stage: int, minutes: float, ends_at: float, kind: str = "work",
                      target: str = "", expect: str = "") -> None:
        """The one thing Pip is busy with in real time: work on a project, a walk, or reading (project_id = book)."""
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO work_session (id, project_id, stage, minutes, started_at, ends_at, "
                            "kind, target, expect) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (project_id, stage, minutes, time.time(), ends_at, kind, target, expect))
            self.db.commit()

    def end_session(self) -> None:
        with self.lock:
            self.db.execute("DELETE FROM work_session")
            self.db.commit()

    def add_xp(self, craft: str, minutes: float) -> None:
        with self.lock:
            self.db.execute("INSERT INTO skills VALUES (?, ?) ON CONFLICT(craft) DO UPDATE SET xp = xp + excluded.xp",
                            (craft, minutes))
            self.db.commit()

    def add_ability_xp(self, shares: dict[str, float]) -> None:
        with self.lock:
            for name, xp in shares.items():
                self.db.execute("INSERT INTO abilities VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET xp = xp + excluded.xp",
                                (name, xp))
            self.db.commit()

    def abilities(self) -> dict[str, float]:
        """ability -> xp (minutes of practice)."""
        with self.lock:
            return {r["name"]: r["xp"] for r in self.db.execute("SELECT * FROM abilities ORDER BY xp DESC")}

    def _seed_abilities(self) -> None:
        """One-time: spread the old per-craft xp over a general blend so earlier practice isn't lost."""
        if self.meta("abilities_seeded"):
            return
        total = sum(self.skills().values())
        if total:
            self.add_ability_xp({"handiness": total * 0.4, "precision": total * 0.3, "patience": total * 0.3})
        self.set_meta(abilities_seeded="1")

    def skills(self) -> dict[str, float]:
        """craft -> xp (minutes of practice)."""
        with self.lock:
            return {r["craft"]: r["xp"] for r in self.db.execute("SELECT * FROM skills ORDER BY xp DESC")}

    # --- creations --------------------------------------------------------------
    @staticmethod
    def _creation(row) -> dict:
        return {**dict(row), "spec": json.loads(row["spec"]), "runtime": json.loads(row["runtime"])}

    def add_creation(self, name: str, description: str, project_id: int | None, quality: str, spec: dict,
                     runtime: dict) -> dict:
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO creations (name, description, project_id, quality, spec, runtime, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, description, project_id, quality, json.dumps(spec), json.dumps(runtime), time.time()))
            self.db.commit()
            return self.creation(cur.lastrowid)

    def creation(self, creation_id: int) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM creations WHERE id = ?", (creation_id,)).fetchone()
        return self._creation(row) if row else None

    def creations(self, include_given: bool = False) -> list[dict]:
        """Things Pip has made (and still has, unless include_given)."""
        q = "SELECT * FROM creations" + ("" if include_given else " WHERE given_to IS NULL") + " ORDER BY id"
        with self.lock:
            return [self._creation(r) for r in self.db.execute(q)]

    def give_creation(self, creation_id: int, to: str) -> None:
        with self.lock:
            self.db.execute("UPDATE creations SET given_to = ? WHERE id = ?", (to, creation_id))
            self.db.commit()

    def set_runtime(self, creation_id: int, runtime: dict) -> None:
        with self.lock:
            self.db.execute("UPDATE creations SET runtime = ? WHERE id = ?", (json.dumps(runtime), creation_id))
            self.db.commit()

    def find_creation(self, query: str) -> tuple[dict | None, str]:
        q = str(query).strip().lower().lstrip("#")
        rows = self.creations()
        exact = [c for c in rows if c["name"].lower() == q]
        part = exact or [c for c in rows if q and (q in c["name"].lower() or c["name"].lower() in q)]
        if len(part) == 1:
            return part[0], ""
        if not part:
            return None, f"you haven't made anything called {query!r}"
        return None, "which one? " + ", ".join(c["name"] for c in part)

    # --- characters (companions, neighbors, residents of invented places) ----------------------------
    _CHARACTER_JSON = ("heard", "replies", "life", "told", "upcoming", "wares", "look")

    @classmethod
    def _character(cls, row) -> dict:
        return {**dict(row), **{k: json.loads(row[k]) for k in cls._CHARACTER_JSON}}

    def add_character(self, name: str, kind: str, creation_id: int | None, persona: str, chatter_minutes: float,
                      next_chatter_at: float, about: str = "", place: str = "") -> dict:
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO characters (name, kind, creation_id, persona, chatter_minutes, next_chatter_at, ts, about, "
                "place) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (name, kind, creation_id, persona, chatter_minutes,
                                                              next_chatter_at, time.time(), about, place))
            self.db.commit()
            return self._character(self.db.execute("SELECT * FROM characters WHERE id = ?", (cur.lastrowid,)).fetchone())

    def characters(self, kind: str | None = None) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM characters ORDER BY id").fetchall()
        return [self._character(r) for r in rows if kind is None or r["kind"] == kind]

    # --- modules (docs/DESIGN-modules.md) ----------------------------------------------
    _MODULE_JSON = ("manifest", "state", "offers", "facts", "lines", "report", "budget")

    def _module(self, row) -> dict:
        return {k: json.loads(row[k]) if k in self._MODULE_JSON else row[k] for k in row.keys()}

    def add_module(self, **fields) -> int:
        vals = {k: json.dumps(v) if k in self._MODULE_JSON else v for k, v in fields.items()}
        with self.lock:
            cur = self.db.execute(f"INSERT INTO modules ({', '.join(vals)}) VALUES ({', '.join('?' for _ in vals)})", tuple(vals.values()))
            self.db.commit()
            return cur.lastrowid

    def module(self, module_id: int) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM modules WHERE id = ?", (module_id,)).fetchone()
        return self._module(row) if row else None

    def modules(self, status: str | tuple | None = None) -> list[dict]:
        """Oldest first (the order hooks run in), optionally only those with a status (or one of several)."""
        statuses = (status,) if isinstance(status, str) else status
        q = "SELECT * FROM modules" + (f" WHERE status IN ({', '.join('?' for _ in statuses)})" if statuses else "") + " ORDER BY id"
        with self.lock:
            return [self._module(r) for r in self.db.execute(q, statuses or ())]

    def update_module(self, module_id: int, **fields) -> None:
        vals = {k: json.dumps(v) if k in self._MODULE_JSON else v for k, v in fields.items()}
        with self.lock:
            self.db.execute(f"UPDATE modules SET {', '.join(f'{k} = ?' for k in vals)} WHERE id = ?", (*vals.values(), module_id))
            self.db.commit()

    def add_module_call(self, module_id: int, ts: float, hook: str, ok: bool, ms: int, summary: str, keep: int = 200) -> None:
        """One hook call, for the module's history (the newest `keep` are kept)."""
        with self.lock:
            self.db.execute("INSERT INTO module_calls (module_id, ts, hook, ok, ms, summary) VALUES (?, ?, ?, ?, ?, ?)",
                            (module_id, ts, hook, int(ok), ms, summary))
            self.db.execute("DELETE FROM module_calls WHERE module_id = ? AND id NOT IN "
                            "(SELECT id FROM module_calls WHERE module_id = ? ORDER BY id DESC LIMIT ?)", (module_id, module_id, keep))
            self.db.commit()

    def module_calls(self, module_id: int, limit: int = 50) -> list[dict]:
        with self.lock:
            return [dict(r) | {"ok": bool(r["ok"])} for r in self.db.execute(
                "SELECT ts, hook, ok, ms, summary FROM module_calls WHERE module_id = ? ORDER BY id DESC LIMIT ?", (module_id, limit))]

    def update_character(self, character_id: int, **fields) -> None:
        vals = {k: json.dumps(v) if k in self._CHARACTER_JSON else v for k, v in fields.items()}
        with self.lock:
            self.db.execute(f"UPDATE characters SET {', '.join(f'{k} = ?' for k in vals)} WHERE id = ?",
                            (*vals.values(), character_id))
            self.db.commit()

    def find_character(self, query: str) -> dict | None:
        q = str(query).strip().lower()
        rows = self.characters()
        hit = [c for c in rows if c["name"].lower() == q] or \
              [c for c in rows if q and (q in c["name"].lower() or c["name"].lower() in q)]
        return hit[0] if len(hit) == 1 else None

    # --- bookmarks (the library) -----------------------------------------------------
    def bookmark(self, book_id: int) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM bookmarks WHERE book_id = ?", (book_id,)).fetchone()
        return dict(row) if row else None

    def bookmarks(self, include_finished: bool = True) -> list[dict]:
        """Books Pip has read in, most recently read first."""
        q = "SELECT * FROM bookmarks" + ("" if include_finished else " WHERE finished = 0 AND unreadable = 0")
        with self.lock:
            return [dict(r) for r in self.db.execute(q + " ORDER BY last_read DESC")]

    def set_bookmark(self, book_id: int, title: str, **fields) -> None:
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO bookmarks (book_id, title) VALUES (?, ?)", (book_id, title))
            if fields:
                self.db.execute(f"UPDATE bookmarks SET {', '.join(f'{k} = ?' for k in fields)} WHERE book_id = ?",
                                (*fields.values(), book_id))
            self.db.commit()

    # --- letters ----------------------------------------------------------------------
    @staticmethod
    def _letter(row) -> dict:
        return {**dict(row), "parcel": json.loads(row["parcel"]) if row["parcel"] else None}

    def add_letter(self, sender: str, recipient: str, text: str, deliver_at: float, enclosed: str = "",
                   parcel: dict | None = None, reply_to: int | None = None, gist: str = "") -> dict:
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO letters (ts, sender, recipient, text, enclosed, parcel, deliver_at, reply_to, gist) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (time.time(), sender, recipient, text, enclosed,
                                                       json.dumps(parcel) if parcel else None, deliver_at, reply_to, gist))
            self.db.commit()
            return self._letter(self.db.execute("SELECT * FROM letters WHERE id = ?", (cur.lastrowid,)).fetchone())

    def letters(self, between: str | None = None, limit: int = 50, undelivered: bool = False) -> list[dict]:
        """Newest `limit` letters (optionally only to/from one name, or only those still on the way), oldest first."""
        q, args = "SELECT * FROM letters WHERE 1=1", []
        if between:
            q += " AND (sender = ? OR recipient = ?)"
            args += [between, between]
        if undelivered:
            q += " AND delivered_at IS NULL"
        with self.lock:
            rows = self.db.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
        return [self._letter(r) for r in reversed(rows)]

    def update_letter(self, letter_id: int, **fields) -> None:
        with self.lock:
            self.db.execute(f"UPDATE letters SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                            (*fields.values(), letter_id))
            self.db.commit()

    def letters_since(self, sender: str, since: float) -> int:
        """How many letters `sender` has written since `since` (for the per-day cap)."""
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM letters WHERE sender = ? AND ts > ?", (sender, since)).fetchone()[0]

    def letters_since_parcel(self, since: float) -> int:
        """How many parcels have been sent to Pip since `since`."""
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM letters WHERE parcel IS NOT NULL AND ts > ?",
                                   (since,)).fetchone()[0]

    def hurry_garden(self, fraction: float, now: float | None = None) -> int:
        """Cut the remaining growing time of every unripe crop by `fraction`. Returns how many were helped."""
        now = now or time.time()
        with self.lock:
            n = self.db.execute("UPDATE garden SET ready_at = ready_at - (ready_at - ?) * ? WHERE ready_at > ?",
                                (now, fraction, now)).rowcount
            self.db.commit()
        return n

    def born_at(self) -> float:
        """When Pip's life here began: the first logged event (or now, for a brand-new world)."""
        b = self.meta("born_at")
        if b:
            return float(b)
        with self.lock:
            first = self.db.execute("SELECT MIN(ts) AS t FROM events").fetchone()["t"]
        b = first or time.time()
        self.set_meta(born_at=b)
        return b

    # --- meta (small key/value facts) ------------------------------------------
    def meta(self, key: str) -> str | None:
        with self.lock:
            row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, **values) -> None:
        with self.lock:
            self.db.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", [(k, str(v)) for k, v in values.items()])
            self.db.commit()

    # --- long-term memory: reflections, people, recall ---------------------------
    def add_reflection(self, kind: str, text: str, importance: int, period_start: float, period_end: float,
                       grounded: bool = True, support: str = "legacy", cites=()) -> int:
        """Store a reflection. `cites` is [(ref_kind, ref_id)], ref_kind 'event' or 'reflection'."""
        now = time.time()
        with self.lock:
            cur = self.db.execute("INSERT INTO reflections (ts, kind, text, importance, period_start, period_end, "
                                  "grounded, support) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                  (now, kind, text, importance, period_start, period_end, int(grounded), support))
            self.db.executemany("INSERT INTO reflection_cites VALUES (?, ?, ?)",
                                [(cur.lastrowid, k, i) for k, i in cites])
            self._index(kind, cur.lastrowid, period_end, text, commit=False, importance=importance)
            self.db.commit()
            return cur.lastrowid

    def reflections(self, kind: str | None = None, limit: int = 20, by_importance: bool = False,
                    grounded: bool | None = None) -> list[dict]:
        """Newest first, or most important first (newest breaking ties). `grounded` filters beliefs from hunches."""
        q, args, where = "SELECT * FROM reflections", [], []
        if kind:
            where.append("kind = ?")
            args.append(kind)
        if grounded is not None:
            where.append("grounded = ?")
            args.append(int(grounded))
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY " + ("importance DESC, id DESC" if by_importance else "id DESC") + " LIMIT ?"
        with self.lock:
            return [dict(r) for r in self.db.execute(q, (*args, limit))]

    def add_expectation(self, kind: str, project_id: int | None, craft: str, subject: str, c: dict, event_id=None) -> int:
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO expectations (ts, kind, project_id, craft, subject, expected, actual, error, surprising, "
                "direction, event_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (time.time(), kind, project_id, craft, subject[:200], str(c["expected"]), str(c["actual"]), c["error"],
                 int(bool(c["surprise"])), c["surprise"], event_id))
            self.db.commit()
            return cur.lastrowid

    def expectations(self, limit: int = 50, since: float | None = None, surprising: bool | None = None) -> list[dict]:
        """Newest first."""
        q, args, where = "SELECT * FROM expectations", [], []
        if since is not None:
            where.append("ts > ?")
            args.append(since)
        if surprising is not None:
            where.append("surprising = ?")
            args.append(int(surprising))
        if where:
            q += " WHERE " + " AND ".join(where)
        with self.lock:
            return [dict(r) for r in self.db.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit))]

    def capability_context(self) -> tuple[dict, dict]:
        """({project id: craft}, {(project id, stage name): abilities}) for events that predate those fields."""
        crafts, stages = {}, {}
        for p in self.projects(limit=500):
            crafts[p["id"]] = p["craft"]
            for st in p["stages"]:
                stages[(p["id"], st["name"])] = st.get("abilities") or []
        return crafts, stages

    def save_capabilities(self, day: str, snapshot: dict) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO capability_snapshots VALUES (?, ?)", (day, json.dumps(snapshot)))
            self.db.commit()

    def capability_snapshots(self, limit: int = 2) -> list[tuple[str, dict]]:
        """Most recent first."""
        with self.lock:
            rows = self.db.execute("SELECT * FROM capability_snapshots ORDER BY day DESC LIMIT ?", (limit,)).fetchall()
        return [(r["day"], json.loads(r["data"])) for r in rows]

    # --- the night pass: decisions and focus ----------------------------------------
    def set_memory_status(self, memory_id: int, status: str, outcome: str | None = None) -> None:
        with self.lock:
            if outcome is None:
                self.db.execute("UPDATE memories SET status = ? WHERE id = ?", (status, memory_id))
            else:
                self.db.execute("UPDATE memories SET status = ?, outcome = ? WHERE id = ?", (status, outcome, memory_id))
            self.db.commit()

    def memory(self, memory_id: int) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return dict(row) if row else None

    def add_decision(self, op: str, target_kind: str, target_id: int | None, args: dict, before: dict, reason: str,
                     cites: list, summary: str, applied: bool) -> int:
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO night_decisions (ts, op, target_kind, target_id, args, before, reason, cites, summary, applied)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (time.time(), op, target_kind, target_id, json.dumps(args), json.dumps(before), reason,
                 json.dumps(cites), summary, int(applied)))
            self.db.commit()
            return cur.lastrowid

    @staticmethod
    def _decision(row) -> dict:
        return {**dict(row), "args": json.loads(row["args"]), "before": json.loads(row["before"]),
                "cites": json.loads(row["cites"])}

    def decision(self, decision_id: int) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM night_decisions WHERE id = ?", (decision_id,)).fetchone()
        return self._decision(row) if row else None

    def decisions(self, limit: int = 20, applied: bool | None = None) -> list[dict]:
        """Newest first."""
        q, args = "SELECT * FROM night_decisions", []
        if applied is not None:
            q += " WHERE applied = ?"
            args.append(int(applied))
        with self.lock:
            return [self._decision(r) for r in self.db.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit))]

    def mark_decision_undone(self, decision_id: int) -> None:
        with self.lock:
            self.db.execute("UPDATE night_decisions SET undone = 1 WHERE id = ?", (decision_id,))
            self.db.commit()

    def unseen_decisions(self, max_age_hours: float, showings: int) -> list[dict]:
        """Applied, not undone decisions Pip hasn't been shown enough times yet."""
        with self.lock:
            rows = self.db.execute("SELECT * FROM night_decisions WHERE applied = 1 AND undone = 0 AND shown < ? AND ts >= ? "
                                   "ORDER BY id", (showings, time.time() - max_age_hours * 3600)).fetchall()
        return [self._decision(r) for r in rows]

    def mark_decisions_shown(self, ids: list[int]) -> None:
        with self.lock:
            self.db.executemany("UPDATE night_decisions SET shown = shown + 1 WHERE id = ?", [(i,) for i in ids])
            self.db.commit()

    def add_focus(self, day: str, text: str, ref_kind: str = "", ref_id: int | None = None) -> int:
        with self.lock:
            cur = self.db.execute("INSERT INTO focus (day, text, ref_kind, ref_id, decided_at) VALUES (?, ?, ?, ?, ?)",
                                  (day, text, ref_kind, ref_id, time.time()))
            self.db.commit()
            return cur.lastrowid

    def focus(self, status: str | None = "open", limit: int = 20) -> list[dict]:
        q, args = "SELECT * FROM focus", []
        if status:
            q += " WHERE status = ?"
            args.append(status)
        with self.lock:
            return [dict(r) for r in reversed(self.db.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall())]

    def close_focus(self, focus_id: int, status: str, note: str = "") -> None:
        with self.lock:
            self.db.execute("UPDATE focus SET status = ?, reviewed_at = ?, note = ? WHERE id = ?",
                            (status, time.time(), note[:200], focus_id))
            self.db.commit()

    def add_work(self, kind: str, title: str, body: str, caption: str = "", location: str = "", pixels: dict | None = None, subject: str = "") -> int:
        """A picture (SVG, already sanitised) or a piece of writing Pip made."""
        now = time.time()
        with self.lock:
            cur = self.db.execute("INSERT INTO works (ts, kind, title, body, caption, location, pixels, subject) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                  (now, kind, title, body, caption, location, json.dumps(pixels) if pixels else "", subject))
            text = f"{title}. {caption}" + (f" {body}" if kind == "writing" else "")
            self._index(f"work:{kind}", cur.lastrowid, now, text.strip(), commit=False, importance=5)
            self.db.commit()
            return cur.lastrowid

    def revise_work(self, work_id: int, body: str, title: str | None = None, caption: str | None = None, pixels: dict | None = None,
                    subject: str | None = None) -> int:
        """Replace a drawing with Pip's redrawing of it; returns how many times it has been redrawn."""
        with self.lock:
            row = self.db.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
            title = title or row["title"]
            caption = row["caption"] if caption is None else caption
            subject = row["subject"] if subject is None else subject
            self.db.execute("UPDATE works SET body = ?, title = ?, caption = ?, pixels = ?, subject = ?, revisions = revisions + 1 WHERE id = ?",
                            (body, title, caption, json.dumps(pixels) if pixels else "", subject, work_id))
            self._index(f"work:{row['kind']}", work_id, row["ts"], f"{title}. {caption}".strip(), commit=False)
            self.db.commit()
            return row["revisions"] + 1

    def work(self, work_id: int) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
        return dict(row) if row else None

    def pictures(self, limit: int = 4) -> list[dict]:
        """The newest pixel pictures, with their grids, for the world view (pictures drawn in SVG have no grid and aren't here)."""
        with self.lock:
            rows = self.db.execute("SELECT id, title, subject, pixels FROM works WHERE kind = 'drawing' AND pixels != '' ORDER BY id DESC LIMIT ?", (limit,))
            return [{"id": r["id"], "title": r["title"], "subject": r["subject"], **json.loads(r["pixels"])} for r in rows]

    def picture_of(self, subject: str = "", title: str = "") -> dict | None:
        """The grid of the newest pixel picture of a creation (by name), or with a title (ignoring case): how that creation looks, or what a copy shows."""
        col, val = ("subject", subject) if subject else ("title", title)
        with self.lock:
            r = self.db.execute(f"SELECT pixels FROM works WHERE kind = 'drawing' AND pixels != '' AND lower({col}) = lower(?) ORDER BY id DESC LIMIT 1",
                                (val,)).fetchone()
        return json.loads(r["pixels"]) if r else None

    def works(self, kind: str | None = None, limit: int = 50, since: float | None = None) -> list[dict]:
        """Newest first, without the bodies' weight for pictures (the SVG is fetched by id)."""
        q, args, where = "SELECT id, ts, kind, title, caption, location, CASE WHEN kind = 'writing' THEN body ELSE '' END AS body FROM works", [], []
        if kind:
            where.append("kind = ?")
            args.append(kind)
        if since is not None:
            where.append("ts >= ?")
            args.append(since)
        if where:
            q += " WHERE " + " AND ".join(where)
        with self.lock:
            return [dict(r) for r in self.db.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit))]

    def add_outreach(self, kind: str, channel: str, conversation: str, text: str, status: str, error: str = "",
                     ts: float | None = None) -> int:
        with self.lock:
            cur = self.db.execute("INSERT INTO outreach (ts, kind, channel, conversation, text, status, error) "
                                  "VALUES (?, ?, ?, ?, ?, ?, ?)",
                                  (ts or time.time(), kind, channel, conversation, text, status, error[:300]))
            self.db.commit()
            return cur.lastrowid

    def outreach_rows(self, limit: int = 50, kind: str | None = None, since: float | None = None,
                      statuses: tuple = ()) -> list[dict]:
        """Newest first."""
        q, args, where = "SELECT * FROM outreach", [], []
        if kind:
            where.append("kind = ?")
            args.append(kind)
        if since is not None:
            where.append("ts >= ?")
            args.append(since)
        if statuses:
            where.append("status IN (%s)" % ",".join("?" * len(statuses)))
            args += list(statuses)
        if where:
            q += " WHERE " + " AND ".join(where)
        with self.lock:
            return [dict(r) for r in self.db.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit))]

    def add_find(self, place: str, item: str, ts: float | None = None) -> None:
        with self.lock:
            self.db.execute("INSERT INTO place_finds (place, item, times, last_ts) VALUES (?, ?, 1, ?) "
                            "ON CONFLICT(place, item) DO UPDATE SET times = times + 1, last_ts = excluded.last_ts",
                            (place, item.lower(), ts or time.time()))
            self.db.commit()

    def finds_at(self, place: str) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(
                "SELECT * FROM place_finds WHERE place = ? ORDER BY times DESC, last_ts DESC", (place,))]

    def found_where(self, item_name: str) -> list[dict]:
        """Places Pip has found something like `item_name` (shares a meaningful word), most often first."""
        with self.lock:
            rows = [dict(r) for r in self.db.execute("SELECT * FROM place_finds ORDER BY times DESC, last_ts DESC")]
        return [r for r in rows if self.related(item_name, r["item"])]

    # --- invented places (see invented_places.py) --------------------------------------
    PLACE_JSON = ("aliases", "hours", "verbs", "loot", "mentions", "on_account")

    def _place(self, row) -> dict:
        return {**dict(row), **{k: json.loads(row[k]) for k in self.PLACE_JSON}}

    def add_place(self, key: str, core: str, **fields) -> dict:
        vals = {"key": key, "core": core, **{k: json.dumps(v) if k in self.PLACE_JSON else v for k, v in fields.items()}}
        with self.lock:
            self.db.execute(f"INSERT INTO places ({', '.join(vals)}) VALUES ({', '.join('?' for _ in vals)})", tuple(vals.values()))
            self.db.commit()
        return self.place_row(key)

    def place_row(self, key: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM places WHERE key = ?", (key,)).fetchone()
        return self._place(row) if row else None

    def map_positions(self) -> dict[str, tuple[float, float]]:
        """Where each place sits on the map (see worldmap.py); a place keeps its spot once it has one."""
        with self.lock:
            return {r["key"]: (r["x"], r["y"]) for r in self.db.execute("SELECT * FROM map_places ORDER BY placed_at, key")}

    def set_map_position(self, key: str, x: float, y: float) -> None:
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO map_places (key, x, y, placed_at) VALUES (?, ?, ?, ?)", (key, x, y, time.time()))
            self.db.commit()

    def place_rows(self) -> list[dict]:
        with self.lock:
            return [self._place(r) for r in self.db.execute("SELECT * FROM places ORDER BY created_at, key")]

    def update_place(self, key: str, **fields) -> None:
        vals = {k: json.dumps(v) if k in self.PLACE_JSON else v for k, v in fields.items()}
        with self.lock:
            self.db.execute(f"UPDATE places SET {', '.join(f'{k} = ?' for k in vals)} WHERE key = ?", (*vals.values(), key))
            self.db.commit()

    def add_turning(self, score: int, signals: list, start: float, end: float) -> int:
        with self.lock:
            cur = self.db.execute("INSERT INTO turning_points (ts, period_start, period_end, score, signals) "
                                  "VALUES (?, ?, ?, ?, ?)", (time.time(), start, end, score, json.dumps(signals)))
            self.db.commit()
            return cur.lastrowid

    def turning_points(self, limit: int = 20) -> list[dict]:
        """Flagged candidates, newest first."""
        with self.lock:
            rows = self.db.execute("SELECT * FROM turning_points ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(r), "signals": json.loads(r["signals"])} for r in rows]

    def save_day_stats(self, day: str, stats: dict) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO day_stats VALUES (?, ?)", (day, json.dumps(stats)))
            self.db.commit()

    def day_stats(self, limit: int = 3) -> list[tuple[str, dict]]:
        """The most recent days' counts, oldest first."""
        with self.lock:
            rows = self.db.execute("SELECT * FROM day_stats ORDER BY day DESC LIMIT ?", (limit,)).fetchall()
        return [(r["day"], json.loads(r["data"])) for r in reversed(rows)]

    def _backfill_portraits(self) -> None:
        """The portrait used to be one overwritten value; keep the current one as the first version."""
        portrait = self.meta("self_portrait")
        if portrait and not self.reflections("portrait", limit=1):
            end = float(self.meta("last_reflection_ts") or time.time())
            self.add_reflection("portrait", portrait, 5, 0, end, support="legacy")

    def reflection_cites(self, reflection_id: int) -> list[tuple[str, int]]:
        with self.lock:
            return [(r["ref_kind"], r["ref_id"]) for r in self.db.execute(
                "SELECT ref_kind, ref_id FROM reflection_cites WHERE reflection_id = ?", (reflection_id,))]

    def event_text(self, event_id: int) -> str | None:
        """What an event said, as Pip would remember it (the text recall indexes), or None."""
        with self.lock:
            row = self.db.execute("SELECT kind, data FROM events WHERE id = ?", (event_id,)).fetchone()
        return recall_text(row["kind"], json.loads(row["data"])) if row else None

    def reflection_text(self, reflection_id: int) -> str | None:
        with self.lock:
            row = self.db.execute("SELECT text FROM reflections WHERE id = ?", (reflection_id,)).fetchone()
        return row["text"] if row else None

    def senders(self) -> list[str]:
        """Everyone who has ever sent Pip a message (visitors by name, neighbors' letters)."""
        with self.lock:
            return [r["sender"] for r in self.db.execute("SELECT DISTINCT sender FROM inbox")]

    def people(self) -> list[dict]:
        """Everyone Pip has notes on, most recently seen first."""
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM people ORDER BY last_seen DESC")]

    def upsert_person(self, name: str, notes: str, seen: float) -> None:
        with self.lock:
            self.db.execute("INSERT INTO people VALUES (?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET "
                            "notes = excluded.notes, last_seen = MAX(last_seen, excluded.last_seen)",
                            (name, notes, seen, seen))
            self._index("person", name, seen, f"{name}: {notes}", commit=False, data={"name": name}, importance=5)
            self.db.commit()

    def _index(self, source: str, ref, ts: float, text: str, commit: bool = True, data: dict | None = None,
               importance: int = 3, fresh: bool = True) -> None:
        """(Re)index one remembered thing for recall. Caller holds the lock. A fresh write also records its context (where Pip was,
        with whom, doing what, feeling how: see reminders.py); writing an existing memory again (an edit) counts as a use of it."""
        self.db.execute("DELETE FROM recall_index WHERE source = ? AND ref = ?", (source, str(ref)))
        self.db.execute("INSERT INTO recall_index (text, source, ref, ts) VALUES (?, ?, ?, ?)",
                        (text, source, str(ref), ts))
        if fresh:
            row = self.db.execute("SELECT uses FROM memory_context WHERE source = ? AND ref = ?", (source, str(ref))).fetchone()
            if row:
                self._add_uses(source, str(ref), json.loads(row["uses"]), time.time())
            else:
                ctx = self._context_now(source, data or {})
                self.db.execute("INSERT INTO memory_context (source, ref, ts, place, people, activity, mood, feeling, project, importance, uses) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (source, str(ref), ts, ctx["place"], json.dumps(ctx["people"]), ctx["activity"], ctx["mood"],
                                 ctx["feeling"], ctx["project"], importance, json.dumps([ts])))
        if commit:
            self.db.commit()

    @staticmethod
    def _people_in(source: str, data: dict) -> list[str]:
        """The people a remembered thing is about: who wrote, spoke, was spoken to or told Pip something."""
        keys = ("sender", "to", "by") + (("name",) if source in ("event:companion", "person") else ())
        names = [str(data[k]).strip() for k in keys if isinstance(data.get(k), str) and data[k].strip()]
        return list(dict.fromkeys(n for n in names if n.lower() not in ("pip", "a visitor")))

    def _context_now(self, source: str, data: dict) -> dict:
        """Where Pip is, with whom, doing what, feeling how: a memory's context, captured as it is written."""
        from . import places
        from .emotions import BASELINE, NOTABLE
        a = self.db.execute("SELECT * FROM agent WHERE id = 1").fetchone()
        sess = self.db.execute("SELECT * FROM work_session WHERE id = 1").fetchone()
        place = None if sess and sess["kind"] == "walk" else a["location"]
        people = self._people_in(source, data) + [c["name"] for c in places.company_at(self, place)]
        project = None
        if sess and sess["kind"] in ("work", "experiment"):
            r = self.db.execute("SELECT name FROM projects WHERE id = ?", (sess["project_id"],)).fetchone()
            project = r["name"] if r else None
        excess = {r["name"]: r["value"] - BASELINE[r["name"]] for r in self.db.execute("SELECT name, value FROM emotions")}
        feeling = max(excess, key=excess.get, default=None)
        return {"place": place, "people": list(dict.fromkeys(people)), "activity": a["activity"],
                "mood": a["mood"], "feeling": feeling if feeling and excess[feeling] >= NOTABLE else None,
                "project": project}

    def _add_uses(self, source: str, ref: str, uses: list, now: float) -> None:
        self.db.execute("UPDATE memory_context SET uses = ?, faded = 0 WHERE source = ? AND ref = ?",
                        (json.dumps((uses + [now])[-USES_KEPT:]), source, ref))

    def _backfill_memory_context(self) -> None:
        """Memories written before contexts were kept: who they were about and how much they mattered (where and how Pip was are unknown)."""
        have = {(r["source"], r["ref"]) for r in self.db.execute("SELECT source, ref FROM memory_context")}
        for r in self.db.execute("SELECT source, ref, ts FROM recall_index").fetchall():
            if (r["source"], r["ref"]) in have:
                continue
            data = {}
            if r["source"].startswith("event:"):
                e = self.db.execute("SELECT data, importance FROM events WHERE id = ?", (int(r["ref"]),)).fetchone()
                data, importance = (json.loads(e["data"]), e["importance"] or 3) if e else ({}, 3)
            elif r["source"].startswith("note:"):
                importance = NOTE_IMPORTANCE.get(r["source"][5:], 3)
            elif r["source"] == "person":
                data, importance = {"name": r["ref"]}, 5
            elif r["source"].startswith("work:"):
                importance = 5
            else:
                e = self.db.execute("SELECT importance FROM reflections WHERE id = ?", (int(r["ref"]),)).fetchone()
                importance = e["importance"] if e else 5
            ts = float(r["ts"])
            self.db.execute("INSERT INTO memory_context (source, ref, ts, people, importance, uses) VALUES (?, ?, ?, ?, ?, ?)",
                            (r["source"], r["ref"], ts, json.dumps(self._people_in(r["source"], data)), importance, json.dumps([ts])))
        self.db.execute("INSERT OR REPLACE INTO meta VALUES ('memory_context', '1')")

    # --- memory contexts (reminders.py) ----------------------------------
    @staticmethod
    def _ctx(row) -> dict:
        d = dict(row)
        d["people"], d["uses"], d["shown_with"] = json.loads(d["people"]), json.loads(d["uses"]), json.loads(d["shown_with"])
        return d

    def memory_context(self, source: str, ref) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM memory_context WHERE source = ? AND ref = ?", (source, str(ref))).fetchone()
        return self._ctx(row) if row else None

    def memory_contexts(self, faded: bool | None = None) -> list[dict]:
        q = "SELECT * FROM memory_context" + ("" if faded is None else " WHERE faded = ?")
        with self.lock:
            return [self._ctx(r) for r in self.db.execute(q, () if faded is None else (int(faded),))]

    def use_memories(self, keys, now: float | None = None) -> None:
        """Pip used these memories (recalled them, or took up a reminder): each use makes them easier to bring to mind."""
        now = now or time.time()
        with self.lock:
            for source, ref in keys:
                row = self.db.execute("SELECT uses FROM memory_context WHERE source = ? AND ref = ?", (source, str(ref))).fetchone()
                if row:
                    self._add_uses(source, str(ref), json.loads(row["uses"]), now)
            self.db.commit()

    def mark_shown(self, keys, now: float, cue_with: list[str]) -> None:
        with self.lock:
            self.db.executemany("UPDATE memory_context SET shown_at = ?, shown_with = ? WHERE source = ? AND ref = ?",
                                [(now, json.dumps(cue_with), s, str(r)) for s, r in keys])
            self.db.commit()

    def set_faded(self, keys) -> None:
        with self.lock:
            self.db.executemany("UPDATE memory_context SET faded = 1 WHERE source = ? AND ref = ?", [(s, str(r)) for s, r in keys])
            self.db.commit()

    def recall_scored(self, words: list[str], limit: int) -> list[dict]:
        """Like recall, but every match with its BM25 score (lower is better), best first."""
        terms = list(dict.fromkeys(words))[:24]           # already plain words (reminders.words)
        if not terms:
            return []
        match = " OR ".join(f'"{t}"*' for t in terms)
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT text, source, ref, ts, bm25(recall_index) AS score FROM recall_index "
                                                     "WHERE recall_index MATCH ? ORDER BY score LIMIT ?", (match, limit))]

    def recall_text_of(self, source: str, ref) -> str | None:
        with self.lock:
            row = self.db.execute("SELECT text FROM recall_index WHERE source = ? AND ref = ?", (source, str(ref))).fetchone()
        return row["text"] if row else None

    def memories_about(self, people: list[str], place: str | None, project: str | None, limit: int) -> list[dict]:
        """The newest remembered things that share a person, the place or the project with the situation."""
        where, args = [], []
        for p in people:
            where.append("c.people LIKE ?")
            args.append(f'%{json.dumps(p)}%')
        if place:
            where.append("c.place = ?")
            args.append(place)
        if project:
            where.append("c.project = ?")
            args.append(project)
        if not where:
            return []
        with self.lock:
            return [dict(r) for r in self.db.execute(
                "SELECT r.text, r.source, r.ref, r.ts FROM memory_context c JOIN recall_index r ON r.source = c.source AND r.ref = c.ref "
                f"WHERE c.faded = 0 AND ({' OR '.join(where)}) ORDER BY c.ts DESC LIMIT ?", (*args, limit))]

    def _normalize_crafts(self) -> None:
        """Older plans stored long craft names ('clockmaking (gear train, escap'); fold them into the core skill."""
        for r in self.db.execute("SELECT id, craft FROM projects").fetchall():
            if craft_name(r["craft"]) != r["craft"]:
                self.db.execute("UPDATE projects SET craft = ? WHERE id = ?", (craft_name(r["craft"]), r["id"]))
        for r in self.db.execute("SELECT craft, xp FROM skills").fetchall():
            if craft_name(r["craft"]) != r["craft"]:
                self.db.execute("DELETE FROM skills WHERE craft = ?", (r["craft"],))
                self.db.execute("INSERT INTO skills VALUES (?, ?) ON CONFLICT(craft) DO UPDATE SET xp = xp + excluded.xp",
                                (craft_name(r["craft"]), r["xp"]))

    def _backfill_recall(self) -> None:
        """(Re)build the recall index from everything stored. Runs when RECALL_INDEX_VERSION changes."""
        self.db.execute("DELETE FROM recall_index")
        for r in self.db.execute("SELECT * FROM memories").fetchall():
            text = r["text"] + (f" (done: {r['outcome']})" if r["status"] == "done" and r["outcome"] else "")
            self._index(f"note:{r['section']}", r["id"], r["ts"], text, commit=False, fresh=False)
        marks = ",".join("?" * len(RECALL_EVENT_KINDS))
        for r in self.db.execute(f"SELECT * FROM events WHERE kind IN ({marks})", RECALL_EVENT_KINDS).fetchall():
            if text := recall_text(r["kind"], json.loads(r["data"])):
                self._index(f"event:{r['kind']}", r["id"], r["ts"], text, commit=False, fresh=False)
        for r in self.db.execute("SELECT * FROM reflections").fetchall():
            self._index(r["kind"], r["id"], r["period_end"], r["text"], commit=False, fresh=False)
        for r in self.db.execute("SELECT * FROM people").fetchall():
            self._index("person", r["name"], r["last_seen"], f"{r['name']}: {r['notes']}", commit=False, fresh=False)
        self.db.execute("INSERT OR REPLACE INTO meta VALUES ('recall_indexed', ?)", (RECALL_INDEX_VERSION,))

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        """The best matches for `query` (BM25 over plain words, prefix-matched), returned oldest first."""
        terms = [w for w in re.findall(r"[a-z0-9]+", str(query).lower()) if len(w) > 1 and w not in STOP_WORDS][:12]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"*' for t in dict.fromkeys(terms))
        with self.lock:
            rows = self.db.execute("SELECT text, source, ref, ts FROM recall_index WHERE recall_index MATCH ? "
                                   "ORDER BY bm25(recall_index) LIMIT ?", (match, limit)).fetchall()
        return sorted((dict(r) for r in rows), key=lambda r: float(r["ts"]))

    # --- usage / budget ----------------------------------------------
    def add_usage(self, input_tokens: int, output_tokens: int) -> None:
        day = date.today().isoformat()
        with self.lock:
            self.db.execute(
                "INSERT INTO usage (day, input_tokens, output_tokens, calls) VALUES (?, ?, ?, 1) "
                "ON CONFLICT(day) DO UPDATE SET input_tokens = input_tokens + excluded.input_tokens, "
                "output_tokens = output_tokens + excluded.output_tokens, calls = calls + 1",
                (day, input_tokens, output_tokens),
            )
            self.db.commit()

    def usage_today(self) -> dict:
        with self.lock:
            r = self.db.execute("SELECT * FROM usage WHERE day = ?", (date.today().isoformat(),)).fetchone()
        used = dict(r) if r else {"day": date.today().isoformat(), "input_tokens": 0, "output_tokens": 0, "calls": 0}
        used["total_tokens"] = used["input_tokens"] + used["output_tokens"]
        used["budget"] = self.s.daily_token_budget
        return used

    def budget_exceeded(self) -> bool:
        return self.usage_today()["total_tokens"] >= self.s.daily_token_budget
