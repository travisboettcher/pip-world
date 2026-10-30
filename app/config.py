import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)


def _parse_people(raw: str) -> dict:
    """'@morgan:example.org=Morgan, @jade:example.org' -> {'@morgan:example.org': 'Morgan', '@jade:example.org': 'Jade'}"""
    out = {}
    for part in (raw or "").split(","):
        uid, _, name = part.strip().partition("=")
        if uid.strip():
            out[uid.strip()] = name.strip() or uid.strip().lstrip("@").split(":")[0].capitalize()
    return out


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name) or default)


@dataclass
class Settings:
    db_path: str = "/data/agent.db"
    persona_path: str = "/srv/persona.md"
    persona_default_path: str = "/srv/persona.default.md"

    llm_backend: str = "anthropic"
    llm_model: str = "claude-haiku-5-5"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_effort: str = "low"
    llm_max_tokens: int = 2048
    max_calls_per_tick: int = 3

    pacing: str = "heartbeat_events"
    heartbeat_seconds: float = 300
    tick_seconds: float = 120
    min_tick_interval: float = 15
    monitor_seconds: float = 30

    daily_token_budget: int = 5_000_000
    garden_plots: int = 3
    garden_plots_max: int = 8           # most plots Pip can ever have (it can clear more than it starts with)
    moment_window_minutes: float = 60  # how far back a notable moment can be offered for the diary
    moment_showings: int = 3           # how many ticks a moment is offered before it's dropped
    garden_speed: float = 1.0  # >1 grows crops faster (testing / impatience)
    work_speed: float = 1.0    # >1 makes work sessions end sooner than real time
    max_active_projects: int = 3
    companion_replies_per_hour: int = 4  # caps Pip <-> companion back-and-forth
    reflect_hour: int = 3              # local hour after which Pip's nightly reflection runs (fallback when it hasn't slept)
    verify_insights: bool = True       # one small GM call a night checks that insights follow from what they cite
    firsts_max_age_hours: float = 24   # a first older than this is no longer offered as new
    firsts_showings: int = 3           # how many ticks a first is shown
    firsts_shown: int = 5              # most firsts listed at once
    night_pass: str = "apply"          # off | log (decide and record, don't act) | apply
    max_night_ops: int = 3
    wild_places: list[str] = field(default_factory=lambda: ["woods", "junkyard"])  # places to gather at
    outreach: str = "on"                # off | on | log (record, don't deliver)
    outreach_channels: list[str] = field(default_factory=list)   # e.g. ["matrix"]; the first is primary; empty = no outside world
    outreach_per_day: int = 2           # new conversations Pip may start per local day
    outreach_min_gap_hours: float = 3
    outreach_max_chars: int = 240
    outreach_reply_max_chars: int = 1500
    outreach_failures_per_day: int = 3
    works_per_day: int = 6              # pictures and pieces of writing Pip may finish per local day
    works_min_gap_minutes: float = 10
    sleep: bool = True                 # day/night rhythm and the sleep tool
    bedtime_hour: int = 22             # night runs from bedtime to wake_hour (local time)
    wake_hour: int = 6
    reflect_max_chars: int = 12000     # how much of the day a reflection reads (newest kept)
    neighbor: bool = True              # invent a neighbor who writes letters
    letter_delay_minutes: float = 120  # how long a letter takes each way (+-30%)
    neighbor_writes_every_hours: float = 30
    letters_per_day: int = 3           # Pip's letters per 24 h
    parcels_per_day: int = 1           # parcels the neighbor may send per 24 h
    library_path: str = "/library"     # a Calibre library (read-only); the library place exists only if it's there
    walk_minutes: float = 10           # how long it takes to walk between places
    read_chars_per_minute: int = 700   # how much text a reading session covers
    tools: list[str] = field(default_factory=list)
    tavily_api_key: str = ""
    # Matrix channel (see matrix.py): the homeserver, Pip's account and token, the one room, and who may talk to Pip
    matrix_homeserver: str = ""
    matrix_user_id: str = ""
    matrix_access_token: str = field(default="", repr=False)
    matrix_room_id: str = ""
    matrix_allowed: dict = field(default_factory=dict)   # {"@morgan:server": "Morgan"}

    # Stat dynamics, per hour
    hunger_per_hour: float = 0.08
    energy_per_hour: float = 0.05
    recover_per_hour: float = 0.30
    sleep_recover_per_hour: float = 0.25
    work_energy_per_hour: float = 0.05  # extra drain during a work session
    hunger_alert: float = 0.8
    energy_alert: float = 0.2

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        return cls(
            db_path=e("DB_PATH", "/data/agent.db"),
            persona_path=e("PERSONA_PATH", "/srv/persona.md"),
            llm_backend=e("LLM_BACKEND") or "anthropic",
            llm_model=e("LLM_MODEL") or "claude-haiku-5-5",
            llm_base_url=e("LLM_BASE_URL", ""),
            llm_api_key=e("LLM_API_KEY", ""),
            llm_effort=e("LLM_EFFORT", "low"),
            llm_max_tokens=_int("LLM_MAX_TOKENS", 2048),
            max_calls_per_tick=_int("MAX_CALLS_PER_TICK", 3),
            pacing=e("PACING") or "heartbeat_events",
            heartbeat_seconds=_float("HEARTBEAT_SECONDS", 300),
            tick_seconds=_float("TICK_SECONDS", 120),
            min_tick_interval=_float("MIN_TICK_INTERVAL", 15),
            daily_token_budget=_int("DAILY_TOKEN_BUDGET", 5_000_000),
            garden_plots=_int("GARDEN_PLOTS", 3),
            garden_plots_max=_int("GARDEN_PLOTS_MAX", 8),
            moment_window_minutes=_float("MOMENT_WINDOW_MINUTES", 60),
            moment_showings=_int("MOMENT_SHOWINGS", 3),
            garden_speed=_float("GROW_SPEED", 1.0),
            work_speed=_float("WORK_SPEED", 1.0),
            max_active_projects=_int("MAX_ACTIVE_PROJECTS", 3),
            companion_replies_per_hour=_int("COMPANION_REPLIES_PER_HOUR", 4),
            reflect_hour=_int("REFLECT_HOUR", 3),
            verify_insights=(e("VERIFY_INSIGHTS") or "1") not in ("0", "false", "no"),
            firsts_max_age_hours=_float("FIRSTS_MAX_AGE_HOURS", 24),
            firsts_showings=_int("FIRSTS_SHOWINGS", 3),
            firsts_shown=_int("FIRSTS_SHOWN", 5),
            night_pass=(e("NIGHT_PASS") or "apply").lower() if (e("NIGHT_PASS") or "apply").lower() in ("off", "log", "apply") else "apply",
            max_night_ops=_int("MAX_NIGHT_OPS", 3),
            wild_places=[w.strip() for w in (e("WILD_PLACES") if e("WILD_PLACES") is not None else "woods,junkyard").split(",") if w.strip()],
            outreach=(e("OUTREACH") or "on").lower() if (e("OUTREACH") or "on").lower() in ("off", "on", "log") else "on",
            outreach_channels=[c.strip() for c in (e("OUTREACH_CHANNELS") or "").split(",") if c.strip()],
            outreach_per_day=_int("OUTREACH_PER_DAY", 2),
            outreach_min_gap_hours=_float("OUTREACH_MIN_GAP_HOURS", 3),
            outreach_max_chars=_int("OUTREACH_MAX_CHARS", 240),
            outreach_reply_max_chars=_int("OUTREACH_REPLY_MAX_CHARS", 1500),
            outreach_failures_per_day=_int("OUTREACH_FAILURES_PER_DAY", 3),
            works_per_day=_int("WORKS_PER_DAY", 6),
            works_min_gap_minutes=_float("WORKS_MIN_GAP_MINUTES", 10),
            sleep=(e("SLEEP") or "1") not in ("0", "false", "no"),
            bedtime_hour=_int("BEDTIME_HOUR", 22),
            wake_hour=_int("WAKE_HOUR", 6),
            sleep_recover_per_hour=_float("SLEEP_RECOVER_PER_HOUR", 0.25),
            reflect_max_chars=_int("REFLECT_MAX_CHARS", 12000),
            neighbor=(e("NEIGHBOR") or "1") not in ("0", "false", "no"),
            letter_delay_minutes=_float("LETTER_DELAY_MINUTES", 120),
            neighbor_writes_every_hours=_float("NEIGHBOR_WRITES_EVERY_HOURS", 30),
            letters_per_day=_int("LETTERS_PER_DAY", 3),
            parcels_per_day=_int("PARCELS_PER_DAY", 1),
            library_path=e("LIBRARY_PATH") or "/library",
            walk_minutes=_float("WALK_MINUTES", 10),
            read_chars_per_minute=_int("READ_CHARS_PER_MINUTE", 700),
            tools=[t.strip() for t in (e("TOOLS") or "say,set_activity,eat,rest,note_to_self,edit_note,resolve_note,use_item,plant,harvest,web_search,start_project,work_on,abandon_project,tend,recall,write_letter,go_to,browse,read,gather,where_to,experiment,revise_plan,sleep,undo_decision,resume_project,send_postcard,draw,write_piece").split(",") if t.strip()],
            tavily_api_key=e("TAVILY_API_KEY", ""),
            matrix_homeserver=e("MATRIX_HOMESERVER", ""),
            matrix_user_id=e("MATRIX_USER_ID", ""),
            matrix_access_token=e("MATRIX_ACCESS_TOKEN", ""),
            matrix_room_id=e("MATRIX_ROOM_ID", ""),
            matrix_allowed=_parse_people(e("MATRIX_ALLOWED", "")),
        )
