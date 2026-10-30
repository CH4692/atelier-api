"""Gate tag-only releases on successful CI for the current main revision."""

import json
import os
import re
import subprocess
from pathlib import Path


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
    """Fail closed for stale or ineligible CI; never exclude legitimate bot work.

    Tag-only releases make no branch commits, so loop prevention follows from
    accepting only main push CI. Neither actor nor commit-message heuristics
    are needed, including when a human reruns a bot's successful CI.
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
    return True


def main() -> None:
    """Write only a boolean decision; never log payloads or credentials."""
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    decision = should_release(event, Path.cwd(), os.environ["GITHUB_REPOSITORY"])
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"release={str(decision).lower()}\n")
    print("Release guard passed." if decision else "Skipping ineligible CI run.")


if __name__ == "__main__":
    main()
