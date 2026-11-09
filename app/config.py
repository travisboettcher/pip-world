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


def _weights(raw, default: tuple) -> tuple:
    """'50,45,5' as three non-negative numbers that are not all zero; anything else is the default."""
    try:
        w = tuple(float(x) for x in str(raw).split(","))
    except ValueError:
        return default
    return w if len(w) == 3 and all(x >= 0 for x in w) and sum(w) > 0 else default


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name) or default)


@dataclass
class Settings:
    db_path: str = "/data/agent.db"
    persona_path: str = "/srv/persona.md"

    llm_backend: str = "anthropic"
    llm_model: str = "claude-haiku-5-5"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_vision: str = ""              # '' = the backend's default; '0' off, '1' on (can the model look at pictures?)
    looks_per_day: int = 20
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
    max_active_projects_cap: int = 5   # most projects at once, however much workshop Pip builds
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
    weather: bool = False              # real weather and daylight (DESIGN-weather.md); needs a provider that is set up
    weather_provider: str = "homeassistant"  # which source: see weather.py (providers register by name)
    hass_url: str = "http://homeassistant.local:8123"            # the Home Assistant provider's settings
    hass_token: str = ""               # a long-lived access token; only weather and sun.sun are ever read, read-only
    weather_entity: str = "weather.forecast_home"
    emotions: str = "on"               # on = tracked and shown to Pip | quiet = tracked only | off (see DESIGN-emotions.md)
    emotion_settle_per_day: int = 3    # times Pip may settle a strong feeling per local day
    bedtime_hour: int = 22             # night runs from bedtime to wake_hour (local time)
    wake_hour: int = 6
    reflect_max_chars: int = 12000     # how much of the day a reflection reads (newest kept)
    neighbor: bool = True              # invent a neighbor who writes letters
    letter_delay_minutes: float = 120  # how long a letter takes each way (+-30%)
    neighbor_writes_every_hours: float = 30
    letters_per_day: int = 3           # Pip's letters per 24 h
    parcels_per_day: int = 1           # parcels the neighbor may send per 24 h
    invented_places_per_day: int = 2   # new heard-of places characters may add per 24 h (DESIGN-invented-places.md)
    invented_places_max: int = 12      # invented places in all, heard-of and real together
    library_path: str = "/library"     # where the books are (read-only); the library place exists only if there is a library there
    library_provider: str = "auto"     # auto | calibre | folder (see library.py); auto tries Calibre, then a plain folder of books
    walk_minutes: float = 10           # how long it takes to walk between places
    read_chars_per_minute: int = 700   # how much text a reading session covers
    tools: list[str] = field(default_factory=list)
    search_provider: str = "tavily"    # which web search source: see search.py (providers register by name)
    tavily_api_key: str = ""     # the Tavily provider's key
    # Matrix channel (see matrix.py): the homeserver, Pip's account and token, the one room, and who may talk to Pip
    matrix_homeserver: str = ""
    matrix_user_id: str = ""
    matrix_access_token: str = field(default="", repr=False)
    matrix_room_id: str = ""
    matrix_allowed: dict = field(default_factory=dict)   # {"@morgan:server": "Morgan"}

    # Happenings: small events from the world (DESIGN-happenings.md). on | log (rolls and writes, applies nothing) | off
    happenings: str = "off"                 # off here so a bare Settings() (tests, library use) rolls nothing; the environment default (from_env) is on
    happenings_chance: float = 0.10          # chance per slot
    happenings_slot_hours: float = 3         # awake time is cut into slots this long, from the wake hour
    happenings_severity: tuple = (50, 45, 5)  # weights: minor, medium, major
    happenings_max_per_day: int = 3

    hemisphere: str = "north"              # which way round the seasons go (happenings; see DESIGN-happenings.md)
    happenings_seasons: bool = True         # what is likelier in which season

    talk_scenes: str = "off"                # on: talk with someone in person runs as its own scene (talk.py); off here so a bare Settings() keeps the old way
    place_scenes: str = "off"               # on: each place gets scene details (walls, roof, palette, setting, props), chosen once (looks.py); off here for tests
    character_looks: str = "off"            # on: each neighbor or resident gets a look for the world view, chosen once (looks.py); off here for tests
    character_booths: str = "off"           # on: neighbors sell their own wares at home and at a market one day a week (market.py); off here for tests
    reminders: str = "off"                  # on: old memories come to mind by themselves (reminders.py); log: chosen and logged, not shown; off here for tests
    reminders_shown: int = 2                # slots in a world turn (a conversation scene has one)
    remind_cooldown_hours: float = 12       # a memory brought to mind stays out of mind this long, unless someone or somewhere new cues it
    wish_share: str = "off"                 # on: wishes that are not things are shared with Pip's friend, one a day (off here so a bare Settings() sends nothing)

    # What is running: set by the image build (VERSION and REVISION build args), shown on the dashboard
    version: str = "dev"
    revision: str = ""

    # The public, read-only view (docs/DESIGN-public-view.md): requests whose Host is listed are served the scrubbed, read-only surface
    public_hosts: list = field(default_factory=list)
    public_redact: list = field(default_factory=list)   # names always shown as "someone" there (visitors and people Pip knows are hidden anyway)

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
            happenings=(e("HAPPENINGS") or "on").lower() if (e("HAPPENINGS") or "on").lower() in ("on", "log", "off") else "on",
            happenings_chance=max(0.0, min(1.0, _float("HAPPENINGS_CHANCE", 0.10))),
            happenings_slot_hours=max(0.5, _float("HAPPENINGS_SLOT_HOURS", 3)),
            happenings_severity=_weights(e("HAPPENINGS_SEVERITY"), (50, 45, 5)),
            happenings_max_per_day=_int("HAPPENINGS_MAX_PER_DAY", 3),
            hemisphere=(e("HEMISPHERE") or "north").lower() if (e("HEMISPHERE") or "north").lower() in ("north", "south") else "north",
            happenings_seasons=(e("HAPPENINGS_SEASONS") or "on").lower() not in ("off", "0", "false", "no"),
            talk_scenes=(e("TALK_SCENES") or "on").lower() if (e("TALK_SCENES") or "on").lower() in ("on", "off") else "on",
            place_scenes=(e("PLACE_SCENES") or "on").lower() if (e("PLACE_SCENES") or "on").lower() in ("on", "off") else "on",
            character_looks=(e("CHARACTER_LOOKS") or "on").lower() if (e("CHARACTER_LOOKS") or "on").lower() in ("on", "off") else "on",
            character_booths=(e("CHARACTER_BOOTHS") or "on").lower() if (e("CHARACTER_BOOTHS") or "on").lower() in ("on", "off") else "on",
            reminders=(e("REMINDERS") or "on").lower() if (e("REMINDERS") or "on").lower() in ("on", "log", "off") else "on",
            reminders_shown=_int("REMINDERS_SHOWN", 2),
            remind_cooldown_hours=_float("REMIND_COOLDOWN_HOURS", 12),
            wish_share=(e("WISH_SHARE") or "on").lower() if (e("WISH_SHARE") or "on").lower() in ("on", "off") else "on",
            version=e("PIP_VERSION") or "dev",
            revision=(e("PIP_REVISION") or "")[:7],
            public_hosts=[h.split(":")[0].strip().lower() for h in (e("PUBLIC_HOSTS") or "").split(",") if h.strip()],
            public_redact=[n.strip() for n in (e("PUBLIC_REDACT") or "").split(",") if n.strip()],
            persona_path=e("PERSONA_PATH", "/srv/persona.md"),
            llm_backend=e("LLM_BACKEND") or "anthropic",
            llm_model=e("LLM_MODEL") or "claude-haiku-5-5",
            llm_base_url=e("LLM_BASE_URL", ""),
            llm_api_key=e("LLM_API_KEY", ""),
            llm_effort=e("LLM_EFFORT", "low"),
            llm_vision=e("LLM_VISION", ""),
            looks_per_day=_int("LOOKS_PER_DAY", 20),
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
            max_active_projects_cap=_int("MAX_ACTIVE_PROJECTS_CAP", 5),
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
            weather=(e("WEATHER") or "0") not in ("0", "false", "no", "off"),
            weather_provider=(e("WEATHER_PROVIDER") or "homeassistant").strip().lower(),
            hass_url=e("HASS_URL") or "http://homeassistant.local:8123",
            hass_token=e("HASS_TOKEN") or "",
            weather_entity=e("WEATHER_ENTITY") or "weather.forecast_home",
            emotions=(e("EMOTIONS") or "on").lower() if (e("EMOTIONS") or "on").lower() in ("on", "quiet", "off") else "on",
            emotion_settle_per_day=_int("EMOTION_SETTLE_PER_DAY", 3),
            bedtime_hour=_int("BEDTIME_HOUR", 22),
            wake_hour=_int("WAKE_HOUR", 6),
            sleep_recover_per_hour=_float("SLEEP_RECOVER_PER_HOUR", 0.25),
            reflect_max_chars=_int("REFLECT_MAX_CHARS", 12000),
            neighbor=(e("NEIGHBOR") or "1") not in ("0", "false", "no"),
            letter_delay_minutes=_float("LETTER_DELAY_MINUTES", 120),
            neighbor_writes_every_hours=_float("NEIGHBOR_WRITES_EVERY_HOURS", 30),
            letters_per_day=_int("LETTERS_PER_DAY", 3),
            parcels_per_day=_int("PARCELS_PER_DAY", 1),
            invented_places_per_day=_int("INVENTED_PLACES_PER_DAY", 2),
            invented_places_max=_int("INVENTED_PLACES_MAX", 12),
            library_path=e("LIBRARY_PATH") or "/library",
            library_provider=(e("LIBRARY_PROVIDER") or "auto").strip().lower(),
            walk_minutes=_float("WALK_MINUTES", 10),
            read_chars_per_minute=_int("READ_CHARS_PER_MINUTE", 700),
            tools=[t.strip() for t in (e("TOOLS") or "say,set_activity,eat,rest,note_to_self,edit_note,resolve_note,use_item,plant,harvest,web_search,start_project,work_on,abandon_project,tend,recall,write_letter,go_to,browse,read,gather,where_to,experiment,revise_plan,sleep,undo_decision,resume_project,send_postcard,draw,write_piece,look,settle,buy,sell,pay,feel").split(",") if t.strip()],
            search_provider=(e("SEARCH_PROVIDER") or "tavily").strip().lower(),
            tavily_api_key=e("TAVILY_API_KEY", ""),
            matrix_homeserver=e("MATRIX_HOMESERVER", ""),
            matrix_user_id=e("MATRIX_USER_ID", ""),
            matrix_access_token=e("MATRIX_ACCESS_TOKEN", ""),
            matrix_room_id=e("MATRIX_ROOM_ID", ""),
            matrix_allowed=_parse_people(e("MATRIX_ALLOWED", "")),
        )
