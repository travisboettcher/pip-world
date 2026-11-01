# Design: real weather and daylight

Status (2026-11-01): built and deployed. Home Assistant is the first provider; the source is pluggable (see Providers). Roadmap: "Real weather / daylight from Home Assistant (harmless sensors only)".

## Goal
The sky over the homelab is the sky over Pip's garden. Pip is told the real conditions and sunrise/sunset, and the weather nudges
the garden a little. Nothing in the house can be read beyond the weather, and nothing can be controlled.

## Providers
Where the weather comes from is a provider, chosen by `WEATHER_PROVIDER` (default `homeassistant`). `app/weather.py` is everything that does not
care about the source: the `Weather` reading, how it is worded, the growing-time factors, keeping the last reading in the state's meta table,
and the throttled refresh. A provider is a small class registered with `@weather.register("name")`, built from the settings on each refresh,
with:
- `ready`: whether it is set up (e.g. a token is present); if not, nothing is requested.
- `async fetch(http=None) -> Weather | None`: one reading, or `None` if the source has nothing usable. Exceptions are fine: the engine
  keeps the last good reading and tries again at the next refresh.

Providers report conditions in the names of `weather.CONDITIONS` (Home Assistant's vocabulary is the common denominator); anything else is shown in
plain words with no effect on the garden. To add a source (say Open-Meteo, which needs only a latitude and longitude, no key), write
`weather_<name>.py` with its mapping from the source's codes to those condition names, register it, and import it at the bottom of `weather.py`.

## Source and safety: the Home Assistant provider
`app/weather_homeassistant.py` talks to Home Assistant (`http://home-assistant:8123`, same `docker_default` network), which already has the `met`
weather and `sun` integrations. It reads exactly two entities with read-only GETs:
- `GET /api/states/<WEATHER_ENTITY>` (default `weather.forecast_home`): `state` (condition), `attributes.temperature`, `temperature_unit`.
- `GET /api/states/sun.sun`: `attributes.next_rising`, `attributes.next_setting`, `state` (`above_horizon` / `below_horizon`).

The entity ids are fixed in code (the weather one is a setting); there is no tool and no code path that calls another entity or any service.
HA only issues long-lived tokens with the owner's full power, so the token is a secret in `.env` (`HASS_TOKEN`, gitignored) and the module is
deliberately tiny. `WEATHER=on|off` turns the feature on (off by default).

## What Pip gets
1. **Perception**, one line near the time line: `Outside: light rain, 8 C; the sun sets at 4:52 PM.` Unknown or failed reads add nothing
   (never an error in the prompt). Temperature is converted to what HA reports; the condition is mapped to plain words.
2. **Garden**: a crop's growing time is multiplied by a small factor when it is planted (never re-scaled afterwards, so state stays simple):
   rain and snow help or hinder within a capped +-15%. See the table in `weather.py`; `GROW_SPEED` still applies on top.
3. The creations' GM prompts (radio bulletins, DESIGN-abilities.md) may be handed the same one-line summary as flavour.

Not in this step: sunset moving bedtime, and storms damaging plots (that belongs with LLM-free random events).

## Engine
- `app/weather.py`: `Weather` (with `line()` and `grow_factor`), `save`/`current` (a reading older than an hour is ignored), `perception`,
  `grow_factor`, the provider registry, and `async refresh(state, settings, now)`: at most one request every 10 minutes; a failure keeps the
  last good reading.
- `app/weather_homeassistant.py`: the provider (`parse` is pure and tested).
- `settings.weather`, `settings.weather_provider`, and the provider's own (`hass_url`, `hass_token`, `weather_entity`).
- Perception reads the stored reading only (the tick must never wait on a network call); the refresh runs in the monitor pass.

## Tests
Core (`test_weather.py`): line wording, the grow factor table and its cap, storage and staleness, refresh throttling and failure handling against a
fake registered provider, the registry, and the garden planting time with and without weather. Home Assistant (`test_weather_homeassistant.py`):
parsing (units, unknown condition, missing attributes) and a check that only the two entity paths are ever requested, with the token.
