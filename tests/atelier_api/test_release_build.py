"""Verify tag-only releases and distribution versions in disposable Git repositories."""

import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from scripts.check_release_artifacts import verify_artifacts
from scripts.check_release_guard import git

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def release_tree(tmp_path):
    tmp_path = tmp_path / "repository"
    tmp_path.mkdir()
    for name in ("pyproject.toml", "README.md", ".gitignore", "uv.lock"):
        shutil.copy2(PROJECT_ROOT / name, tmp_path / name)
    shutil.copytree(
        PROJECT_ROOT / "src",
        tmp_path / "src",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "Release test")
    git(tmp_path, "config", "user.email", "release@example.invalid")
    git(
        tmp_path,
        "remote",
        "add",
        "origin",
        "https://github.com/example/atelier-api.git",
    )
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "feat: initial release")
    return tmp_path


def semantic_release(repository: Path) -> subprocess.CompletedProcess[str]:
    """Disable every remote write and build only local temporary tags."""
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "semantic_release",
            "version",
            "--no-commit",
            "--no-push",
            "--no-vcs-release",
            "--skip-build",
        ],
        cwd=repository,
        env={**os.environ, "GH_TOKEN": "", "GITHUB_TOKEN": ""},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize(
    "message,expected",
    [
        ("docs: improve instructions", "0.1.0"),
        ("refactor: simplify code", "0.1.0"),
        ("test: cover edge case", "0.1.0"),
        ("chore: maintenance", "0.1.0"),
        ("ci: improve validation", "0.1.0"),
        ("fix: correct lookup", "0.1.1"),
        ("feat: introduce archive", "0.2.0"),
        ("feat!: replace contract", "0.2.0"),
        ("fix: replace contract\n\nBREAKING CHANGE: incompatible response", "0.2.0"),
    ],
)
def test_semantic_release_tags_original_commit_without_branch_changes(
    release_tree, message, expected
):
    git(release_tree, "tag", "v0.1.0")
    (release_tree / "change.txt").write_text(message)
    git(release_tree, "add", "change.txt")
    git(release_tree, "commit", "-m", message)
    tested = git(release_tree, "rev-parse", "HEAD")
    result = semantic_release(release_tree)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(release_tree, "rev-parse", "HEAD") == tested
    assert git(release_tree, "rev-parse", "main") == tested
    if expected != "0.1.0":
        assert git(release_tree, "rev-parse", f"v{expected}^{{commit}}") == tested
        assert (release_tree / "CHANGELOG.md").exists()
    else:
        assert git(release_tree, "tag", "--list") == "v0.1.0"
    assert (release_tree / "pyproject.toml").read_bytes() == (
        PROJECT_ROOT / "pyproject.toml"
    ).read_bytes()


def test_first_release_and_repeated_release_are_safe(release_tree):
    tested = git(release_tree, "rev-parse", "HEAD")
    first = semantic_release(release_tree)
    assert first.returncode == 0, first.stdout + first.stderr
    assert git(release_tree, "rev-parse", "v0.1.0^{commit}") == tested
    repeated = semantic_release(release_tree)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert git(release_tree, "tag", "--list") == "v0.1.0"
    assert git(release_tree, "rev-parse", "HEAD") == tested


def build(repository: Path, output: Path, pretend_version: str | None = None) -> None:
    environment = {**os.environ}
    environment.pop("SETUPTOOLS_SCM_PRETEND_VERSION", None)
    if pretend_version is not None:
        environment["SETUPTOOLS_SCM_PRETEND_VERSION"] = pretend_version
    uv = shutil.which("uv")
    assert uv is not None
    result = subprocess.run(
        [uv, "build", "--offline", "--out-dir", str(output)],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_pretag_build_tag_checkout_and_gitless_source_archive_agree(
    release_tree, tmp_path
):
    pretag = tmp_path / "pretag"
    build(release_tree, pretag, "0.1.0")
    verify_artifacts(pretag, "0.1.0")
    git(release_tree, "tag", "v0.1.0")
    tagged = tmp_path / "tagged"
    build(release_tree, tagged)
    verify_artifacts(tagged, "0.1.0")
    installed = tmp_path / "installed"
    uv = shutil.which("uv")
    assert uv is not None
    subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--offline",
            "--no-deps",
            "--target",
            str(installed),
            str(next(tagged.glob("*.whl"))),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    # Use the built wheel's code and metadata with the existing test dependencies.
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); from importlib.metadata import version; from atelier_api.main import app; from atelier_api.version import software_version; assert version('atelier-api') == software_version() == app.openapi()['info']['version'] == '0.1.0'",
            str(installed),
        ],
        cwd=tmp_path,
        env={**os.environ, "DATABASE_URL": "sqlite://"},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    with pytest.raises(ValueError, match="planned release"):
        verify_artifacts(tagged, "0.2.0")
    archive = next(tagged.glob("*.tar.gz"))
    unpacked = tmp_path / "unpacked"
    unpacked.mkdir()
    with tarfile.open(archive) as source:
        source.extractall(unpacked, filter="data")
    gitless = next(unpacked.iterdir())
    rebuilt = tmp_path / "rebuilt"
    # Build only a wheel: an sdist already exists and no Git checkout is required.
    uv = shutil.which("uv")
    assert uv is not None
    result = subprocess.run(
        [uv, "build", "--offline", "--wheel", "--out-dir", str(rebuilt)],
        cwd=gitless,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    shutil.copy2(archive, rebuilt / archive.name)
    verify_artifacts(rebuilt, "0.1.0")


def test_missing_artifacts_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="exactly one wheel"):
        verify_artifacts(tmp_path, "0.1.0")
