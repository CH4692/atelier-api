"""Validate Conventional Commit and pre-1.0 semantic release policy."""

import os
import subprocess
import tomllib
from pathlib import Path

from semantic_release.commit_parser.conventional import ConventionalCommitParser
from semantic_release.enums import LevelBump
from semantic_release.version.algorithm import _increment_version
from semantic_release.version.version import Version

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def release_configuration() -> dict:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as file:
        return tomllib.load(file)["tool"]["semantic_release"]


def test_release_workflow_uses_one_token_for_checkout_push_and_upload():
    workflow = (PROJECT_ROOT / ".github/workflows/release.yaml").read_text()
    assert "uses: actions/create-github-app-token@v3" in workflow
    assert "if: vars.RELEASE_APP_CLIENT_ID" not in workflow
    assert "secrets.GITHUB_TOKEN" not in workflow
    assert "owner: ${{ github.repository_owner }}" in workflow
    assert "repositories: atelier-api" in workflow
    assert "client-id: ${{ vars.RELEASE_APP_CLIENT_ID }}" in workflow
    assert "private-key: ${{ secrets.RELEASE_APP_PRIVATE_KEY }}" in workflow
    assert "permission-contents: write" in workflow
    assert "id-token:" not in workflow
    assert "      contents: read" in workflow
    credential = "${{ steps.release-token.outputs.token }}"
    assert workflow.count(f"token: {credential}") == 3
    assert workflow.count(f"github_token: {credential}") == 2
    assert "ref: main" in workflow
    assert "fetch-depth: 0" in workflow
    ci = (PROJECT_ROOT / ".github/workflows/ci.yaml").read_text()
    assert ci.count("fetch-depth: 0") == ci.count("uses: actions/checkout@v6")


def test_release_workflow_preserves_ci_guards_and_prevents_release_loops():
    workflow = (PROJECT_ROOT / ".github/workflows/release.yaml").read_text()
    assert "conclusion == 'success'" in workflow
    assert "event == 'push'" in workflow
    assert "head_branch == 'main'" in workflow
    assert "github.event.workflow_run.head_commit.message" not in workflow
    assert (
        "github.event.workflow_run.head_repository.full_name == github.repository"
        in workflow
    )
    assert "python3 scripts/check_release_guard.py" in workflow
    assert "commit: false" in workflow
    assert "tag: true" in workflow
    assert "push: true" in workflow
    assert "strict: false" in workflow
    assert "if: steps.guard.outputs.release == 'true'" in workflow
    assert "branches:" not in workflow.split("permissions:", 1)[0]
    assert "tags:" not in (PROJECT_ROOT / ".github/workflows/ci.yaml").read_text()
    assert "cancel-in-progress: false" in workflow
    assert "$TESTED_SHA" in workflow
    assert "if: steps.release.outputs.released == 'true'" in workflow


def test_release_configuration_has_one_canonical_version_source():
    config = release_configuration()
    assert config["version_toml"] == []
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)
    assert "version" not in project["project"]
    assert project["project"]["dynamic"] == ["version"]
    assert project["tool"]["hatch"]["version"]["source"] == "vcs"
    assert project["build-system"]["build-backend"] == "hatchling.build"
    assert config["branches"] == {"main": {"match": "main", "prerelease": False}}
    assert config["tag_format"] == "v{version}"
    assert "uv lock" not in config["build_command"]
    assert "git add" not in config["build_command"]
    assert (
        'SETUPTOOLS_SCM_PRETEND_VERSION="$NEW_VERSION" uv build'
        in config["build_command"]
    )


def test_release_build_installs_only_the_pinned_build_tool():
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)
    (uv_requirement,) = project["project"]["optional-dependencies"]["build"]
    command = project["tool"]["semantic_release"]["build_command"]
    assert f"python -m pip install --only-binary=:all: '{uv_requirement}'" in command
    assert "pip install -e" not in command
    assert 'python scripts/check_release_artifacts.py "$NEW_VERSION"' in command


def test_release_build_stops_if_tool_installation_fails(tmp_path):
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\nexit 23\n")
    python.chmod(0o755)
    for tool in ("uv", "git"):
        executable = tmp_path / tool
        executable.write_text('#!/bin/sh\necho unexpected > "$RELEASE_TEST_MARKER"\n')
        executable.chmod(0o755)
    marker = tmp_path / "unexpected"
    result = subprocess.run(
        ["/bin/bash", "-c", release_configuration()["build_command"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(tmp_path),
            "PACKAGE_NAME": "atelier-api",
            "RELEASE_TEST_MARKER": str(marker),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 23
    assert not marker.exists()


def test_conventional_commits_have_explicit_release_levels():
    parser = ConventionalCommitParser()
    assert parser.parse_message("feat: add work orders").bump is LevelBump.MINOR
    assert parser.parse_message("fix: correct customer lookup").bump is LevelBump.PATCH
    assert (
        parser.parse_message("perf: reduce customer query count").bump
        is LevelBump.PATCH
    )
    for commit_type in ["docs", "test", "refactor", "chore", "ci"]:
        result = parser.parse_message(f"{commit_type}: update project")
        assert result.bump is LevelBump.NO_RELEASE


def test_breaking_changes_remain_pre_one_until_policy_is_changed():
    config = release_configuration()
    parsed = ConventionalCommitParser().parse_message("feat!: replace customer API")
    assert parsed.bump is LevelBump.MAJOR
    current = Version.parse("0.1.0")
    next_version = _increment_version(
        current,
        current,
        parsed.bump,
        False,
        "rc",
        config["major_on_zero"],
        config["allow_zero_version"],
    )
    assert str(next_version) == "0.2.0"
