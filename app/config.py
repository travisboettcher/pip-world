import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)


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
    moment_window_minutes: float = 60  # how far back a notable moment can be offered for the diary
    moment_showings: int = 3           # how many ticks a moment is offered before it's dropped
    garden_speed: float = 1.0  # >1 grows crops faster (testing / impatience)
    tools: list[str] = field(default_factory=list)
    tavily_api_key: str = ""

    # Stat dynamics, per hour
    hunger_per_hour: float = 0.08
    energy_per_hour: float = 0.05
    recover_per_hour: float = 0.30
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
            moment_window_minutes=_float("MOMENT_WINDOW_MINUTES", 60),
            moment_showings=_int("MOMENT_SHOWINGS", 3),
            garden_speed=_float("GROW_SPEED", 1.0),
            tools=[t.strip() for t in (e("TOOLS") or "say,set_activity,eat,rest,note_to_self,edit_note,resolve_note,use_item,plant,harvest,web_search").split(",") if t.strip()],
            tavily_api_key=e("TAVILY_API_KEY", ""),
        )
