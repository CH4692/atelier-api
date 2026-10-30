"""Gate releases on tested revisions and recognize generated metadata commits."""

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

RELEASE_BOT = "atelier-release-bot[bot]"
RELEASE_FILES = {"pyproject.toml", "uv.lock", "CHANGELOG.md"}


def git(repository: Path, *arguments: str) -> str:
    """Read local Git facts without interpolating event data into shell commands."""
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def should_release(event: dict, repository: Path, expected_repository: str) -> bool:
    """Fail closed for stale revisions and skip only generated release commits.

    Use the original run actor, not triggering_actor: a human rerunning a bot's
    CI must not turn its generated commit into a new release candidate.
    """
    run = event["workflow_run"]
    if (
        event.get("action") != "completed"
        or run.get("name") != "Attelier CI"
        or run.get("conclusion") != "success"
        or run.get("event") != "push"
        or run.get("head_branch") != "main"
        or run.get("head_repository", {}).get("full_name") != expected_repository
        or event.get("repository", {}).get("full_name") != expected_repository
    ):
        return False
    tested = run.get("head_sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", tested):
        raise ValueError("Missing or invalid tested commit SHA")
    if git(repository, "rev-parse", "HEAD") != tested:
        raise ValueError("Checkout does not match the successfully tested commit")
    if git(repository, "rev-parse", "refs/remotes/origin/main") != tested:
        raise ValueError("main advanced after the tested commit; wait for its CI")
    if run.get("actor", {}).get("login") != RELEASE_BOT:
        return True
    config = tomllib.loads((repository / "pyproject.toml").read_text())
    version = config["project"]["version"]
    expected_message = config["tool"]["semantic_release"]["commit_message"].format(
        version=version
    )
    if git(repository, "log", "-1", "--format=%B") != expected_message:
        return True
    parents = git(repository, "rev-list", "--parents", "-n", "1", "HEAD").split()
    if len(parents) != 2:
        return True
    changed = set(
        git(
            repository, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
        ).splitlines()
    )
    return not (changed and changed <= RELEASE_FILES)


def main() -> None:
    """Write only a boolean decision; never log payloads or credentials."""
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    decision = should_release(event, Path.cwd(), os.environ["GITHUB_REPOSITORY"])
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"release={str(decision).lower()}\n")
    print(
        "Release guard passed."
        if decision
        else "Skipping non-release CI run or generated release commit."
    )


if __name__ == "__main__":
    main()
