"""SQLite-backed world state: agent stats, event log, inbox, memories, usage."""
import json
import sqlite3
import threading
import time
from datetime import date

from .config import Settings

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
  text TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, text TEXT NOT NULL,
  section TEXT NOT NULL DEFAULT 'diary',
  status TEXT NOT NULL DEFAULT 'open',
  outcome TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS usage (
  day TEXT PRIMARY KEY, input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0, calls INTEGER NOT NULL DEFAULT 0
);
"""

STAT_FIELDS = ("hunger", "energy", "mood", "location", "activity")
SECTIONS = ("diary", "todo", "wishlist", "ambitions", "learned")
RESOLVABLE = ("todo", "wishlist", "ambitions")  # sections whose items can be crossed off


def clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


class State:
    def __init__(self, settings: Settings, path: str | None = None):
        self.s = settings
        self.lock = threading.RLock()
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
            ):
                if col not in {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            if not self.db.execute("SELECT 1 FROM agent").fetchone():
                self.db.execute(
                    "INSERT INTO agent (id, hunger, energy, mood, location, activity, updated_at) "
                    "VALUES (1, 0.2, 0.9, 'curious', 'workshop', 'idle', ?)",
                    (time.time(),),
                )
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
                self.s.recover_per_hour if a["activity"] == "resting" else -self.s.energy_per_hour
            )
            hunger = clamp(a["hunger"] + self.s.hunger_per_hour * hours)
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
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO events (ts, kind, data) VALUES (?, ?, ?)",
                (time.time(), kind, json.dumps(data)),
            )
            self.db.commit()
            return cur.lastrowid

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

    # --- inbox -------------------------------------------------------
    def add_inbox(self, text: str) -> int:
        with self.lock:
            cur = self.db.execute("INSERT INTO inbox (ts, text) VALUES (?, ?)", (time.time(), text))
            self.db.commit()
            return cur.lastrowid

    def pending_inbox(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM inbox WHERE consumed = 0 ORDER BY id")]

    def consume_inbox(self, ids: list[int]) -> None:
        with self.lock:
            self.db.executemany("UPDATE inbox SET consumed = 1 WHERE id = ?", [(i,) for i in ids])
            self.db.commit()

    # --- memories (the journal) ----------------------------------------
    def add_memory(self, text: str, section: str = "diary") -> int:
        if section not in SECTIONS:
            raise ValueError(f"unknown section {section!r}; options: {list(SECTIONS)}")
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO memories (ts, text, section) VALUES (?, ?, ?)", (time.time(), text, section))
            self.db.commit()
            return cur.lastrowid

    def memories(self, section: str | None = None, status: str | None = None, limit: int = 10) -> list[dict]:
        """Newest `limit` entries matching the filters, returned oldest first."""
        q, args = "SELECT * FROM memories WHERE 1=1", []
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
            self.db.commit()
            return ""

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
