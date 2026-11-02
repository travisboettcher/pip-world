---
name: tdd
description: Test-driven development workflow for this project's Python code (red, green, refactor, then mutation testing). Use when adding a feature, fixing a bug, or changing behaviour in this project's code (anything with a pytest suite).
---

# Test-driven development

Follow the loop in order. Do not write production code before a failing test exists for it.

1. **Understand the behaviour.** Name the one thing that should be true after the change (a quantity drops, a refusal message, an event is logged). Read the nearest existing test file and copy its fixtures and style.
2. **Red.** Write the smallest test that expresses it. Run only that test. Confirm it fails with an assertion about the new behaviour. If it errors for another reason (import, fixture, typo), fix the test until it fails correctly. For a bug, reproduce the bug first.
3. **Green.** Make the minimal change that passes. No extras, no speculative parameters. Run the whole suite, not just the new test.
4. **Refactor.** With everything green, simplify names and duplication in both code and tests. Re-run the suite after each step.
5. **Mutate.** Run mutation testing on the modules you touched and read the survivors:
   - `nice -n 19 .venv/bin/mutmut run --max-children 4 "app.<module>*" && scripts/mutation-gate.sh`
   - One mutation run at a time, never in parallel (including across subagents): it loads every core and can starve the host's networking, DNS included.
   - A survivor is a missing assertion (a boundary, a message, a default, an untested branch). Add a test that kills it, then re-run.
   - The score must be at least 95% for the touched code. An equivalent mutant (no observable difference) may stay; note it.
6. **Commit** the test and the code together.

## Test quality checks
- Assert outcomes the user or engine could observe, not private calls. Check both the changed value *and* what must not change.
- Cover boundaries: zero, one, exactly-at-limit, just-over, empty, missing.
- One reason to fail per test; name the test after the behaviour (`test_work_on_consumes_tool_materials`).
- Never let a test depend on the hour it runs at. A day runs from local midnight, so a test that shifts timestamps by hours or reads `time.time()` can pass in the afternoon and fail at 2 am. Say what you mean instead (the gap has passed, the limit is reached) or pass the time in; CI runs the suite under several timezones to catch it.
- Never weaken, skip or delete a test to get green. Never call real network APIs; use the `fake` backend and in-process fakes.

## When stuck
If a test is hard to write, the code is probably doing too much: extract the decision into a small pure function and test that.
