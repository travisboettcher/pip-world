# CLAUDE.md (pip-world)

Pip's world: a Python/FastAPI app in `app/` (see README.md for usage and docs/ROADMAP.md for what's next). Read the matching
docs/DESIGN-*.md file for an area before changing it. `docker-compose.yml` is the shipped Compose file; `pip-world.hll` is an alternative
source that generates the same service, and `test_public_files.py` keeps the two in agreement.

## Development is test-driven
Use the `tdd` skill. Every behaviour change follows red, green, refactor:
1. **Red**: write a failing test first and run it. Watch it fail *for the reason you expect* (an assertion on the new behaviour, not an
   ImportError or typo). For a bug, the test reproduces the bug before you touch the code.
2. **Green**: write the least code that passes. Run the whole suite.
3. **Refactor** with the suite green, then run mutation testing on what you touched (below).

Rules:
- No production change without a test that fails without it. If something is genuinely untestable, say why in the commit message.
- Tests assert behaviour and state the engine owns (quantities, timers, events, refusals), not implementation details. Use the `fake` LLM
  backend and the in-process fakes; tests never call a real API or the network.
- A bug fix includes its regression test, and the test goes in the file for the module it exercises.
- Don't weaken or delete a test to get green. A surviving mutant is a missing assertion; fix the test.

## Prefer general tools over specific ones
Pip's tool list is small on purpose. Don't add a one-off tool for a single situation (`save_seeds`, `wind_clock`); extend a general one
(`use_item`, `tend`, `go_to`, `say`...) so the new behaviour falls out of what Pip would naturally try. Pip already reaches for
`use_item` with a purpose ("scoop out a few seeds"), so make that purpose work rather than teaching a new verb. Only add a tool when no
general tool can carry the action, and say why in the commit message. Also don't make the world refuse something that would just work in
the real world (a clock can be wound again at any time); fix why Pip does it so often instead.

## Prefer a provider abstraction over tying to a service
Don't wire the engine directly to one external service (Home Assistant, a particular weather API, a mail host, a model vendor). Put the
service behind a small provider interface and make the service one implementation: the core owns the data type, wording, storage,
throttling and failure handling; a provider is a class registered by name that turns the source into that type (see `weather.py` and
`weather_homeassistant.py`, and `llm/` for the model backends). Pick it with a setting (`WEATHER_PROVIDER`), keep each provider's own
settings and its safety limits (which endpoints it may touch) inside it, and test the core against a fake registered provider so the
core never depends on a real service.

## Running tests
```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q                          # unit tests (~15 s)
.venv/bin/pytest -q --cov=app --cov-report=term-missing   # coverage (95% lines at the time of writing)
```

## Mutation testing (95% cutoff)
`mutmut` (config in `setup.cfg`) changes the code in small ways and checks that some test fails. The **mutation score**
(killed / (killed + survived)) must be **at least 95%** for the code you changed.
```sh
nice -n 19 .venv/bin/mutmut run --max-children 4 "app.projects*"   # scope to the modules you touched (a full run is ~20k mutants, ~30 min)
scripts/mutation-gate.sh                     # prints the score from the last run; exits 1 below 95% (MUTATION_MIN overrides)
.venv/bin/mutmut results                     # survivors; `mutmut show <name>` prints the diff, `mutmut browse` is interactive
```
For each survivor either add the assertion that kills it or, if the mutant is equivalent (no observable change), leave it and mention it.
The LLM backends that talk to real APIs (`app/llm/anthropic_backend.py`, `openai_compat.py`) are excluded from mutation.
Run the gate before committing a change to engine code. Never lower the cutoff to make a change pass.

**Run ONE mutation run at a time, always with `--max-children 4` and `nice -n 19`.** `mutmut` defaults to one worker per CPU core, and each worker
runs the test suite. Several runs at once (seven in parallel on 2026-10-31) pushed the load average past 400 and starved the host's networking,
including DNS. This is a shared machine that also serves everything else, so one runaway job takes the whole host down. Subagents must not start their own
mutation runs in parallel either: split the work by module and run the modules one after another.
