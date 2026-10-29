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


def test_release_configuration_has_one_canonical_version_source():
    config = release_configuration()
    assert config["version_toml"] == ["pyproject.toml:project.version:nf"]
    assert config["branches"] == {"main": {"match": "main", "prerelease": False}}
    assert config["tag_format"] == "v{version}"
    assert "uv lock --upgrade-package" in config["build_command"]
    assert "git add uv.lock" in config["build_command"]


def test_release_build_installs_only_the_pinned_build_tool():
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)
    (uv_requirement,) = project["project"]["optional-dependencies"]["build"]
    command = project["tool"]["semantic_release"]["build_command"]
    assert f"python -m pip install --only-binary=:all: '{uv_requirement}'" in command
    assert "pip install -e" not in command
    assert command.strip().endswith("uv build")


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
