"""The engine names no world (docs/DESIGN-world-packs.md, phase 1; CLAUDE.md, "Keep the engine generic"): no string the engine sends to
the model or shows the agent says "Pip". The files still being moved over are listed; the list may only shrink."""
import ast
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"
WORLD_WORDS = re.compile(r"\bPip\b")
NOT_YET: set = set()   # files whose strings still name Pip: none (phase 1b done, 0.32.0); keep it empty


def strings(path: Path) -> list[tuple[int, str]]:
    """Every string literal in a module that isn't a docstring (f-strings' literal parts included)."""
    tree = ast.parse(path.read_text())
    docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    return [(n.lineno, n.value) for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def engine_files():
    for p in sorted(APP.rglob("*.py")):
        if "module_library" not in p.parts and "__pycache__" not in p.parts:
            yield p
    yield APP / "builder" / "api.md"


def offenders(p: Path) -> list[str]:
    if p.suffix == ".md":
        return [f"{i}: {line.strip()[:80]}" for i, line in enumerate(p.read_text().splitlines(), 1) if WORLD_WORDS.search(line)]
    return [f"{n}: {s.strip()[:80]}" for n, s in strings(p) if WORLD_WORDS.search(s)]


@pytest.mark.parametrize("path", list(engine_files()), ids=lambda p: str(p.relative_to(APP)))
def test_the_engine_names_no_world(path):
    rel = str(path.relative_to(APP))
    found = offenders(path)
    if rel in NOT_YET:
        assert found, f"{rel} names no world any more: take it off NOT_YET"
    else:
        assert not found, f"{rel} names Pip (use the pack's agent: world_pack.Agent):\n" + "\n".join(found)


def test_the_narrator_speaks_of_whoever_the_agent_is():
    import asyncio
    from app.gm import GameMaster
    from app.world_pack import Agent
    from tests.test_gm_prompts import report
    from app.llm.fake import FakeBackend

    class Rec(FakeBackend):
        def __init__(self):
            super().__init__([report(title="T", text="t")] * 10)
            self.tasks = []

        async def complete(self, system, messages, tools, max_tokens):
            self.tasks.append(messages[0]["content"])
            return await super().complete(system, messages, tools, max_tokens)

    b = Rec()
    gm = GameMaster(b, None, agent=Agent("Wren", "she", "a survivor"))
    gm.state = type("S", (), {"budget_exceeded": lambda self: False, "add_usage": lambda self, i, o: None, "log": lambda self, *a, **k: None})()
    asyncio.run(gm.use("- a lamp", "light it", "Wren is idle.", [{"name": "tend", "help": "trim it"}]))
    asyncio.run(gm.write_happening("found", "good", "minor", "joy", "", {"period": "evening", "names": []}, []))
    text = "\n".join(b.tasks)
    assert "Wren spends time with one of the things she made" in text and "Pip" not in text


def test_the_engine_speaks_of_the_active_worlds_agent(tmp_path):
    from app import builder as B, commands, happenings as H, world_pack as W
    from app.config import Settings
    from tests.test_world_pack import pack_dir
    try:
        W.set_active(W.load(Settings(world_pack=str(pack_dir(tmp_path)))))
        help_text = commands.answer(None, Settings(), "/help")
        assert "not by Wren" in help_text and "what Wren is doing and how she is" in help_text and "Wren's emotion state" in help_text
        api = B.api()
        assert "Wren said something to one of your voices" in api and "Wren's newest pixel drawings" in api and "Pip" not in api
        assert "AGENT" not in api and "HOME_KEY" not in api
        with pytest.raises(ValueError) as e:
            H._intent({"diary_count": 0, "old_notes": []}, "neutral", "minor", {"kind": "memory"}, None)
        assert str(e.value) == "Wren has no old thought to come back to her"
    finally:
        W.set_active(W.load(Settings()))
    assert "what Pip is doing and how it is" in commands.answer(None, Settings(), "/help")
