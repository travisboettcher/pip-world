"""The shipped defaults carry nothing specific to one household: no person's name, no private host (DESIGN-extract.md)."""
import importlib.machinery
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.channels import FakeChannel
from app.config import Settings
from app.llm.fake import FakeBackend
from app.main import create_app

PIPCHAT = next(p / "pipchat" for p in Path(__file__).resolve().parents if (p / "pipchat").is_file())   # also under mutants/


def load_pipchat(monkeypatch, **env):
    for k in ("PIP_URL", "PIP_NAME"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    loader = importlib.machinery.SourceFileLoader("pipchat_under_test", str(PIPCHAT))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


def test_the_test_channel_has_a_neutral_default_sender():
    assert FakeChannel().allowed == {"u1": "Sam"}


def test_the_dashboard_does_not_assume_who_is_giving_things(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", persona_default_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        page, js = c.get("/ui/index.html").text, c.get("/ui/app.js").text
    assert 'id="g-from" maxlength="40" value="visitor"' in page and "store.get('giver', 'visitor')" in js
    assert "Morgan" not in page and "Morgan" not in js


def test_pipchat_defaults_to_a_local_pip_and_a_neutral_name(monkeypatch):
    mod = load_pipchat(monkeypatch)
    assert mod.DEFAULT_URL == "http://localhost:8000" and mod.DEFAULT_SENDER == "visitor"
    assert "example" not in PIPCHAT.read_text() and "Morgan" not in PIPCHAT.read_text()


def test_pipchat_takes_who_you_are_and_where_pip_is_from_the_environment(monkeypatch):
    mod = load_pipchat(monkeypatch, PIP_NAME="Sam", PIP_URL="http://pip.example:9000")
    assert mod.DEFAULT_SENDER == "Sam" and mod.DEFAULT_URL == "http://pip.example:9000"
