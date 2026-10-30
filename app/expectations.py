"""Expectations and surprise (see DESIGN-expectations.md).

Pip may say what it expects before a work session or an experiment; step durations compare Pip's own minutes guess
with the time actually spent. The engine compares expectation and outcome and records the gap as plain fact
('better than expected', 'longer than expected') - no mood words, no scripted reaction. Everything is deterministic.
"""
SESSION_SCALE = {"blowup": 0, "setback": 1, "slow": 2, "good": 3, "breakthrough": 4}
SESSION_EXPECT = {"well": 3, "slowly": 2, "badly": 1}
SESSION_WORDS = {"blowup": "very badly - it blew up", "setback": "badly - a setback", "slow": "slowly",
                 "good": "well", "breakthrough": "unusually well"}
EXPERIMENT_SCALE = {"nothing": 0, "clue": 1, "insight": 2, "surprise": 2}
EXPERIMENT_EXPECT = {"fails": 0, "partly": 1, "works": 2}
EXPERIMENT_EXPECT_PHRASE = {"fails": "to fail", "partly": "to partly work", "works": "to work"}
EXPERIMENT_WORDS = {"nothing": "it failed", "clue": "it partly worked", "insight": "it worked",
                    "surprise": "it worked, with something unexpected"}
SESSION_SURPRISE = 2     # |ordinal error| at or above this is a surprise
STEP_LONGER, STEP_SHORTER = 1.8, 0.5
CALIBRATION_MIN = 5      # predictions needed before Pip is shown a summary
CALIBRATION_WINDOW = 10
CRAFT_MIN, CRAFT_WINDOW = 3, 5
PROGRESS_WINDOW = 5      # learning progress compares the last N misses with the N before
DIRECTIONS = ("better", "worse")


def _direction(err: float) -> str | None:
    return "better" if err > 0 else "worse" if err < 0 else None


def compare_session(expect: str, verdict: str) -> dict | None:
    if expect not in SESSION_EXPECT or verdict not in SESSION_SCALE:
        return None
    err = SESSION_SCALE[verdict] - SESSION_EXPECT[expect]
    return {"kind": "session", "expected": expect, "actual": SESSION_WORDS[verdict], "error": err,
            "surprise": _direction(err) if abs(err) >= SESSION_SURPRISE else None,
            "phrase": f"you expected it to go {expect}; it went {SESSION_WORDS[verdict]}"}


def compare_experiment(expect: str, outcome: str) -> dict | None:
    if expect not in EXPERIMENT_EXPECT or outcome not in EXPERIMENT_SCALE:
        return None
    err = EXPERIMENT_SCALE[outcome] - EXPERIMENT_EXPECT[expect]
    return {"kind": "experiment", "expected": expect, "actual": EXPERIMENT_WORDS[outcome], "error": err,
            "surprise": _direction(err) if abs(err) == 2 else None,
            "phrase": f"you expected it {EXPERIMENT_EXPECT_PHRASE[expect]}; {EXPERIMENT_WORDS[outcome]}"}


def compare_step(guess: float, actual: float) -> dict | None:
    if not guess or guess <= 0 or actual <= 0:
        return None
    ratio = actual / guess
    surprise = "longer" if ratio >= STEP_LONGER else "shorter" if ratio <= STEP_SHORTER else None
    return {"kind": "step", "expected": f"{round(guess)} min", "actual": f"{round(actual)} min", "error": round(ratio, 2),
            "surprise": surprise, "phrase": f"you guessed {round(guess)} minutes; it took {round(actual)}"}


def calibration(rows: list[dict]) -> list[str]:
    """Plain counts over Pip's latest session/experiment predictions (newest first), or [] if there are too few."""
    rows = [r for r in rows if r["kind"] in ("session", "experiment")][:CALIBRATION_WINDOW]
    if len(rows) < CALIBRATION_MIN:
        return []
    close = sum(1 for r in rows if not r["surprising"])
    lines = [f"Your predictions lately: {close} of {len(rows)} were close."]
    by_craft: dict[str, list[dict]] = {}
    for r in rows:
        by_craft.setdefault(r["craft"] or "your work", []).append(r)
    for craft, rs in by_craft.items():
        rs = rs[:CRAFT_WINDOW]
        if len(rs) < CRAFT_MIN:
            continue
        for word, test in (("worse", lambda e: e < 0), ("better", lambda e: e > 0)):
            n = sum(1 for r in rs if test(r["error"]))
            if n >= 3 and n / len(rs) >= 0.6:
                lines.append(f"In {n} of your last {len(rs)} {craft} predictions it went {word} than you expected.")
    return lines


def learning_progress(rows_by_craft: dict[str, list[float]]) -> list[tuple[str, float, float]]:
    """(craft, earlier mean miss, recent mean miss) for crafts with enough data. Rows are |errors|, newest first."""
    out = []
    for craft, errs in rows_by_craft.items():
        recent, earlier = errs[:PROGRESS_WINDOW], errs[PROGRESS_WINDOW:2 * PROGRESS_WINDOW]
        if len(recent) >= 3 and len(earlier) >= 3:
            out.append((craft, round(sum(earlier) / len(earlier), 1), round(sum(recent) / len(recent), 1)))
    return out
