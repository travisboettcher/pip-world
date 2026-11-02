"""The files a stranger starts from agree with each other: the compose file and the hll both run the *published image*, building from source is an explicit
override, and CI builds that image and pushes it to GHCR (DESIGN-extract.md)."""
import re
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve()
IMAGE = "ghcr.io/travisboettcher/agent-world:latest"


def find_root() -> Path | None:
    for p in HERE.parents:
        for base in (p / "public", p):
            if (base / "docker-compose.yml").is_file() and (base / "agent-world.hll").is_file():
                return base
    return None


ROOT = find_root()
pytestmark = pytest.mark.skipif(ROOT is None, reason="the public files are not part of this checkout")


def load(rel: str) -> dict:
    return yaml.safe_load((ROOT / rel).read_text())


def workflow(name: str) -> dict:
    wf = load(f".github/workflows/{name}")
    wf["on"] = wf.pop(True, wf.get("on"))             # YAML 1.1 reads a bare `on` as true
    return wf


def steps(wf: dict, job: str) -> list[dict]:
    return wf["jobs"][job]["steps"]


def test_the_default_compose_runs_the_published_image_and_does_not_build():
    svc = load("docker-compose.yml")["services"]["agent-world"]
    assert svc["image"] == IMAGE and "build" not in svc
    assert svc["ports"] == ["127.0.0.1:8000:8000"]


def test_the_hll_names_the_same_image():
    hll = (ROOT / "agent-world.hll").read_text()
    assert re.findall(r'^\s*image\s+"([^"]+)"', hll, re.M) == [IMAGE] and "build" not in re.sub(r"#.*", "", hll)


def test_building_from_source_is_an_explicit_override_of_the_same_service():
    override = load("docker-compose.build.yml")
    assert override == {"services": {"agent-world": {"build": "."}}}


def test_the_readme_starts_from_the_image_and_says_how_to_build_instead():
    readme = (ROOT / "README.md").read_text()
    quick = readme.split("## Quick start")[1].split("```sh")[1].split("```")[0]            # the commands a newcomer copies
    assert "docker compose up -d" in quick and "--build" not in quick
    assert "docker-compose.build.yml" in readme and "hllc build agent-world.hll --out docker-compose.yml" in readme
    assert IMAGE.rsplit(":", 1)[0] in readme


def test_ci_runs_the_tests_on_pushes_and_pull_requests_and_proves_the_image_builds():
    wf = workflow("ci.yml")
    assert set(wf["on"]) >= {"push", "pull_request"}
    run = " ".join(s.get("run", "") for s in steps(wf, "test"))
    assert "pytest" in run and "requirements-dev.txt" in run
    build = steps(wf, "image")
    push = [s for s in build if str(s.get("uses", "")).startswith("docker/build-push-action")]
    assert push and push[0]["with"]["push"] is False                                  # CI only proves it builds


def test_the_image_workflow_pushes_to_ghcr_on_main_and_on_version_tags():
    wf = workflow("image.yml")
    assert wf["on"]["push"]["branches"] == ["main"] and wf["on"]["push"]["tags"] == ["v*"]
    assert "pytest" in " ".join(s.get("run", "") for s in steps(wf, "test"))             # the tests gate the push
    job = wf["jobs"]["publish"]
    assert job["needs"] == "test" and job["permissions"] == {"contents": "read", "packages": "write"}
    uses = [str(s.get("uses", "")) for s in job["steps"]]
    assert any(u.startswith("docker/login-action") for u in uses) and any(u.startswith("docker/build-push-action") for u in uses)
    login = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("docker/login-action"))
    assert login["with"]["registry"] == "ghcr.io" and login["with"]["password"] == "${{ secrets.GITHUB_TOKEN }}"
    meta = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("docker/metadata-action"))
    assert meta["with"]["images"] == "ghcr.io/${{ github.repository }}"
    assert "type=raw,value=latest,enable={{is_default_branch}}" in meta["with"]["tags"] and "type=semver,pattern={{version}}" in meta["with"]["tags"]
    push = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("docker/build-push-action"))
    assert push["with"]["push"] is True and push["with"]["platforms"] == "linux/amd64"


def test_every_action_is_pinned_to_a_major_version():
    for name in ("ci.yml", "image.yml"):
        for job in workflow(name)["jobs"].values():
            for s in job["steps"]:
                if "uses" in s:
                    assert re.fullmatch(r"[\w./-]+@v\d+", s["uses"]), s["uses"]
