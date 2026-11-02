"""The example environment file is documentation that must not rot: every variable in it is one the code reads, it loads under Docker
Compose's rules, and the copy shipped with the public files matches the template."""
import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
APP = next(p / "app" for p in HERE.parents if (p / "app" / "config.py").is_file())
READ_BY_A_LIBRARY = {"ANTHROPIC_API_KEY"}    # the Anthropic SDK reads its own key from the environment
FILES = [f for p in HERE.parents for rel in (".env.tpl", "public/.env.example", ".env.example") if (f := p / rel).is_file()]


def active(path: Path) -> list[tuple[str, str]]:
    return [(k, v) for k, _, v in (ln.partition("=") for ln in path.read_text().splitlines() if ln.strip() and not ln.lstrip().startswith("#"))]


def test_there_is_an_example_to_check():
    assert FILES


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name + ":" + p.parent.name)
def test_every_variable_in_the_example_is_one_the_code_reads(path):
    source = "\n".join(f.read_text() for f in APP.rglob("*.py"))
    unread = [k for k, _ in active(path) if k not in READ_BY_A_LIBRARY and f'"{k}"' not in source]
    assert unread == []


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name + ":" + p.parent.name)
def test_the_example_loads_under_compose_rules_and_lists_each_variable_once(path):
    pairs = active(path)
    assert all(re.fullmatch(r"[A-Z][A-Z0-9_]*", k) for k, _ in pairs)
    assert [v for _, v in pairs if " #" in v] == []                     # no trailing comments: `docker run --env-file` would keep them
    keys = [k for k, _ in pairs]
    assert len(keys) == len(set(keys))


def test_the_public_copy_matches_the_template():
    tpl = next((f for f in FILES if f.name == ".env.tpl"), None)
    public = next((f for f in FILES if f.name == ".env.example"), None)
    if not (tpl and public):
        pytest.skip("only one of the two exists")
    body = lambda f, n: f.read_text().split("\n", n)[n]                    # noqa: E731  (skip the leading header comment lines)
    assert active(tpl) == active(public)
    assert body(tpl, 1).strip() == body(public, 3).strip()
