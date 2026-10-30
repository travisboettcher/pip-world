"""SQLite-backed world state: agent stats, event log, inbox, memories, usage."""
import json
import re
import sqlite3
import threading
import time
from datetime import date

from .config import Settings
from .world import KINDS, STARTER_ITEMS, normalize_attrs

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
  outcome TEXT NOT NULL DEFAULT '',
  edited_at REAL
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
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS usage (
  day TEXT PRIMARY KEY, input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0, calls INTEGER NOT NULL DEFAULT 0
);
"""

STAT_FIELDS = ("hunger", "energy", "mood", "location", "activity")
SECTIONS = ("diary", "todo", "wishlist", "ambitions", "learned")
RESOLVABLE = ("todo", "wishlist", "ambitions")  # sections whose items can be crossed off
EDITABLE = tuple(sec for sec in SECTIONS if sec != "diary")  # the diary is a record: never rewritten


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
                ("memories", "edited_at", "REAL"),
            ):
                if col not in {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            if not self.db.execute("SELECT 1 FROM agent").fetchone():
                self.db.execute(
                    "INSERT INTO agent (id, hunger, energy, mood, location, activity, updated_at) "
                    "VALUES (1, 0.2, 0.9, 'curious', 'workshop', 'idle', ?)",
                    (time.time(),),
                )
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

    def events_since(self, ts: float, limit: int = 2000) -> list[dict]:
        """Events newer than ts, oldest first."""
        with self.lock:
            rows = self.db.execute("SELECT * FROM events WHERE ts > ? ORDER BY id ASC LIMIT ?", (ts, limit)).fetchall()
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
            row = self.db.execute("SELECT * FROM items WHERE name = ?", (name,)).fetchone()
            if row:  # same item again: stack it
                self.db.execute("UPDATE items SET qty = qty + ?, description = COALESCE(NULLIF(?, ''), description) "
                                "WHERE id = ?", (qty, description[:200], row["id"]))
            else:
                self.db.execute(
                    "INSERT INTO items (name, description, kind, qty, attrs, ts) VALUES (?, ?, ?, ?, ?, ?)",
                    (name, description[:200], kind, qty, json.dumps(normalize_attrs(name, kind, attrs)), time.time()))
            self.db.commit()
            return self._item(self.db.execute("SELECT * FROM items WHERE name = ?", (name,)).fetchone())

    def items(self) -> list[dict]:
        with self.lock:
            return [self._item(r) for r in self.db.execute("SELECT * FROM items ORDER BY id")]

    def find_item(self, query: str, kind: str | None = None) -> tuple[dict | None, str]:
        """Resolve a loose name ('needle file') to one item. Returns (item, '') or (None, error)."""
        q = str(query).strip().lower()
        rows = [i for i in self.items() if not kind or i["kind"] == kind]
        exact = [i for i in rows if i["name"].lower() == q]
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

    # --- garden ----------------------------------------------------------
    def garden(self, now: float | None = None) -> list[dict]:
        now = now or time.time()
        with self.lock:
            rows = {r["plot"]: dict(r) for r in self.db.execute("SELECT * FROM garden")}
        out = []
        for n in range(1, self.s.garden_plots + 1):
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
