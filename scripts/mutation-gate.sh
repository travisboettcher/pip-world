#!/usr/bin/env bash
# Mutation-score gate: reads the last `mutmut run` and fails below MUTATION_MIN percent (default 95).
# Score = killed / (killed + survived); no-test and skipped mutants are reported but not counted.
set -euo pipefail
cd "$(dirname "$0")/.."
MIN="${MUTATION_MIN:-95}"
MUTMUT="${MUTMUT:-$( [ -x .venv/bin/mutmut ] && echo .venv/bin/mutmut || echo mutmut )}"
$MUTMUT export-cicd-stats >/dev/null 2>&1
python3 - "$MIN" <<'PY'
import json, sys
s = json.load(open("mutants/mutmut-cicd-stats.json"))
killed, survived = s.get("killed", 0), s.get("survived", 0)
timeout, suspicious = s.get("timeout", 0), s.get("suspicious", 0)
untested = s.get("no_tests", 0) + s.get("not_checked", 0)
caught = killed + timeout
total = caught + survived + suspicious
if not total:
    sys.exit("no mutation results; run `mutmut run` first")
score = 100 * caught / total
print(f"mutation score {score:.1f}% (killed {killed}, timeout {timeout}, survived {survived}, suspicious {suspicious}; "
      f"{untested} not checked or without tests) - minimum {sys.argv[1]}%")
sys.exit(0 if score >= float(sys.argv[1]) else 1)
PY
