# Design: real weather and daylight

Status (2026-11-01): designed, not built. Roadmap: "Real weather / daylight from Home Assistant (harmless sensors only)".

## Goal
The sky over the homelab is the sky over Pip's garden. Pip is told the real conditions and sunrise/sunset, and the weather nudges
the garden a little. Nothing in the house can be read beyond the weather, and nothing can be controlled.

## Source and safety
Home Assistant (`http://home-assistant:8123`, same `docker_default` network) already has the `met` weather and `sun` integrations.
Agent-world reads exactly two entities with read-only GETs:
- `GET /api/states/<WEATHER_ENTITY>` (default `weather.forecast_home`): `state` (condition), `attributes.temperature`, `temperature_unit`,
  `humidity`, `wind_speed`.
- `GET /api/states/sun.sun`: `attributes.next_rising`, `attributes.next_setting`, `state` (`above_horizon` / `below_horizon`).

The entity ids are fixed in code (the weather one is a setting); there is no tool and no code path that calls another entity or any
service. HA only issues long-lived tokens with the owner's full power, so the token is a secret in `.env` (`HASS_TOKEN`, gitignored) and
the module is deliberately tiny. `WEATHER=on|off` (default off until a token is set).

## What Pip gets
1. **Perception**, one line near the time line: `Outside: light rain, 8 C; the sun sets at 4:52 PM.` Unknown or failed reads add nothing
   (never an error in the prompt). Temperature is converted to what HA reports; the condition is mapped to plain words.
2. **Garden**: a crop's growing time is multiplied by a small factor when it is planted (never re-scaled afterwards, so state stays simple):
   rain and snow help or hinder within a capped +-15%. See the table in `weather.py`; `GROW_SPEED` still applies on top.
3. The creations' GM prompts (radio bulletins, DESIGN-abilities.md) may be handed the same one-line summary as flavour.

Not in this step: sunset moving bedtime, and storms damaging plots (that belongs with LLM-free random events).

## Engine
- `app/weather.py`: `parse(weather_state, sun_state, now) -> Weather | None` (pure, tested), `Weather.line(now)`, `Weather.grow_factor`, and
  `async fetch(settings, http=None)` with a 10 minute cache and a short timeout. Failures return the last good value for up to 1 hour,
  then `None`.
- `settings.weather`, `settings.hass_url`, `settings.hass_token`, `settings.weather_entity`.
- Perception calls the cache only (the tick must never wait on HA); a background refresh runs in the monitor pass.

## Tests
Parsing (units, unknown condition, missing attributes), line wording, the grow factor table and its cap, cache and fallback behaviour with a
fake client, the garden planting time with and without weather, and a check that the module only ever requests the two entity paths.
