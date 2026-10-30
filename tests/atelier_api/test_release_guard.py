"""Exercise release decisions against disposable repositories, without publishing."""

import json
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

from scripts.check_release_guard import git, should_release

RELEASE_BOT = "atelier-release-bot[bot]"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "CH4692/atelier-api"


def commit(repository: Path, message: str) -> str:
    subprocess.run(["git", "add", "."], cwd=repository, check=True, capture_output=True)
    git(
        repository,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        message,
    )
    return git(repository, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, "init", "-b", "main")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "0.1.0"\n[tool.semantic_release]\ncommit_message = "chore(release): {version} [skip ci]"\n'
    )
    commit(tmp_path, "feat: initial implementation")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    return tmp_path


def event(repository: Path, actor: str = "owner") -> dict:
    # head_commit is deliberately absent: the guard reads the tested Git object.
    return {
        "action": "completed",
        "repository": {"full_name": REPOSITORY},
        "workflow_run": {
            "name": "Attelier CI",
            "conclusion": "success",
            "event": "push",
            "head_branch": "main",
            "head_sha": git(repository, "rev-parse", "HEAD"),
            "head_repository": {"full_name": REPOSITORY},
            "actor": {"login": actor},
            "triggering_actor": {"login": "human-rerunner"},
        },
    }


@pytest.mark.parametrize("actor", ["owner", RELEASE_BOT, "dependabot[bot]"])
def test_successful_main_push_allows_legitimate_changes(repository, actor):
    assert should_release(event(repository, actor), repository, REPOSITORY)


@pytest.mark.parametrize(
    "field,value",
    [
        ("conclusion", "failure"),
        ("conclusion", "cancelled"),
        ("event", "pull_request"),
        ("event", "workflow_dispatch"),
        ("head_branch", "feature"),
        ("name", "Other CI"),
        ("head_repository", {"full_name": "untrusted/fork"}),
    ],
)
def test_ineligible_ci_never_releases(repository, field, value):
    payload = event(repository)
    payload["workflow_run"][field] = value
    assert not should_release(payload, repository, REPOSITORY)


def test_checkout_must_match_tested_sha(repository):
    payload = event(repository)
    (repository / "new.py").write_text("untested = True\n")
    commit(repository, "feat: untested change")
    with pytest.raises(ValueError, match="Checkout does not match"):
        should_release(payload, repository, REPOSITORY)


def test_main_advancing_after_checkout_blocks_release(repository):
    payload = event(repository)
    tested = payload["workflow_run"]["head_sha"]
    (repository / "new.py").write_text("new = True\n")
    advanced = commit(repository, "feat: concurrent push")
    git(repository, "update-ref", "refs/remotes/origin/main", advanced)
    git(repository, "checkout", "--detach", tested)
    with pytest.raises(ValueError, match="main advanced"):
        should_release(payload, repository, REPOSITORY)


@pytest.mark.parametrize("sha", ["", "not-a-sha", "--help"])
def test_missing_or_malformed_sha_fails_closed(repository, sha):
    payload = event(repository)
    payload["workflow_run"]["head_sha"] = sha
    with pytest.raises(ValueError, match="tested commit SHA"):
        should_release(payload, repository, REPOSITORY)


@pytest.mark.parametrize(
    "actor,extra_file,expected",
    [
        (RELEASE_BOT, "CHANGELOG.md", True),
        (RELEASE_BOT, "code.py", True),
        ("owner", "CHANGELOG.md", True),
    ],
)
def test_commit_message_and_actor_do_not_suppress_tested_changes(
    repository, actor, extra_file, expected
):
    (repository / extra_file).write_text("changed\n")
    commit(repository, "chore(release): 0.1.0 [skip ci]")
    git(repository, "update-ref", "refs/remotes/origin/main", "HEAD")
    payload = event(repository, actor)
    payload["workflow_run"]["head_commit"] = {"message": "untrusted payload message"}
    assert should_release(payload, repository, REPOSITORY) is expected


def test_bot_message_prefix_alone_does_not_suppress_release(repository):
    (repository / "CHANGELOG.md").write_text("changed\n")
    commit(repository, "chore(release): fix release infrastructure")
    git(repository, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert should_release(event(repository, RELEASE_BOT), repository, REPOSITORY)


def test_guard_cli_writes_boolean_output(repository, tmp_path):
    payload = tmp_path / "event.json"
    payload.write_text(json.dumps(event(repository)))
    output = tmp_path / "output.txt"
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts/check_release_guard.py")],
        cwd=repository,
        env={
            **os.environ,
            "GITHUB_EVENT_PATH": str(payload),
            "GITHUB_OUTPUT": str(output),
            "GITHUB_REPOSITORY": REPOSITORY,
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text() == "release=true\n"


@pytest.mark.parametrize(
    "client_id,key,expected",
    [
        ("", "", 1),
        ("id", "", 1),
        ("", "private-test-value", 1),
        ("id", "private-test-value", 0),
    ],
)
def test_workflow_credential_validation_fails_without_both_inputs(
    client_id, key, expected
):
    workflow = (PROJECT_ROOT / ".github/workflows/release.yaml").read_text()
    block = workflow.split("- name: Validate release credentials\n", 1)[1].split(
        "\n      - name:", 1
    )[0]
    command = dedent(block.split("run: |\n", 1)[1])
    result = subprocess.run(
        ["/bin/bash", "-e", "-c", command],
        env={
            **os.environ,
            "RELEASE_APP_CLIENT_ID": client_id,
            "RELEASE_APP_PRIVATE_KEY": key,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == expected
    assert "private-test-value" not in result.stdout + result.stderr


def test_empty_token_output_fails_explicitly():
    workflow = (PROJECT_ROOT / ".github/workflows/release.yaml").read_text()
    block = workflow.split("- name: Require GitHub App authentication\n", 1)[1].split(
        "\n      - name:", 1
    )[0]
    command = dedent(block.split("run: |\n", 1)[1])
    result = subprocess.run(
        ["/bin/bash", "-e", "-c", command],
        env={**os.environ, "RELEASE_TOKEN": ""},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 1
    assert "did not produce a token" in result.stdout
