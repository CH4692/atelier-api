"""Verify required CI coverage, failure propagation and report privacy."""

import json
import re
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import yaml

from scripts.report_tests import publish_report

ROOT = Path(__file__).resolve().parents[2]


def workflow():
    # BaseLoader preserves YAML's "on" key rather than interpreting it as a bool.
    return yaml.load(
        (ROOT / ".github/workflows/ci.yaml").read_text(), Loader=yaml.BaseLoader
    )


def test_ci_triggers_and_all_required_jobs():
    ci = workflow()
    assert ci["name"] == "Attelier CI"
    assert ci["on"]["pull_request"]["branches"] == ["main"]
    assert ci["on"]["push"]["branches"] == ["main"]
    assert ci["on"]["merge_group"]["types"] == ["checks_requested"]
    assert ci["permissions"] == {"contents": "read"}
    jobs = ci["jobs"]
    assert set(jobs["required"]["needs"]) == set(jobs) - {"required"}
    assert jobs["required"]["if"] == "always()"
    assert 'job["result"] != "success"' in jobs["required"]["steps"][0]["run"]
    assert "continue-on-error" not in (ROOT / ".github/workflows/ci.yaml").read_text()


def test_ci_runs_all_integration_and_e2e_without_external_credentials():
    ci = workflow()
    test = ci["jobs"]["test"]
    assert test["services"]["postgres"]["image"] == "postgres:17"
    assert test["env"]["TEST_DATABASE_URL"].endswith("/atelier_test")
    command = next(
        step["run"]
        for step in test["steps"]
        if step.get("name") == "Run all PostgreSQL integration and E2E tests"
    )
    assert "make test-integration TEST_WORKERS=2" in command
    makefile = (ROOT / "Makefile").read_text()
    integration = makefile.split("test-integration:\n", 1)[1].split("\n\n", 1)[0]
    assert "pytest tests/integration --require-postgres" in integration
    assert "-m e2e" not in integration
    assert "-k " not in integration
    assert "secrets." not in (ROOT / ".github/workflows/ci.yaml").read_text()
    for name in (
        "R2_ENDPOINT_URL",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
    ):
        assert ci["env"][name] == ""


def test_ci_keeps_build_installation_and_migration_verification():
    jobs = workflow()["jobs"]
    package = "\n".join(
        step.get("run", "") for step in jobs["package-installation"]["steps"]
    )
    assert "uv build" in package
    assert "uv pip install" in package
    assert "-I check_installed_package.py" in package
    migrations = "\n".join(step.get("run", "") for step in jobs["migrations"]["steps"])
    assert "alembic downgrade -1" in migrations
    assert migrations.count("make db-migrate") == 2
    assert migrations.count("make db-check") == 2


def test_reports_remove_credentials_captured_output_and_parameters(tmp_path):
    source = tmp_path / "raw.xml"
    output = tmp_path / "safe.xml"
    summary = tmp_path / "summary.md"
    source.write_text("""<testsuites><testsuite tests="3" time="2.5"><properties><property name="password" value="secret-value"/></properties>
    <testcase name="test_login[secret-value]" classname="tests.auth" time="1"><failure message="secret-value">database credentials secret-value</failure><system-out>secret-value</system-out></testcase>
    <testcase name="test_ok" classname="tests.auth" time="0.5"/>
    <testcase name="test_skip" classname="tests.auth" time="0"><skipped message="secret-value"/></testcase>
    </testsuite></testsuites>""")
    publish_report(source, output, summary)
    for file in (output, summary):
        assert "secret-value" not in file.read_text()
        assert "database credentials" not in file.read_text()
    root = ET.parse(output).getroot()
    assert root.attrib["tests"] == "3"
    assert root.attrib["failures"] == "1"
    assert root.attrib["skipped"] == "1"
    assert root.find("testcase/system-out") is None
    assert "passed: 1" in summary.read_text()
    assert "case-" in summary.read_text()


@pytest.mark.parametrize(
    "status,expected",
    [("failure", 1), ("cancelled", 1), ("skipped", 1), ("success", 0)],
)
def test_required_job_checks_dependency_result(status, expected):
    import os

    script = workflow()["jobs"]["required"]["steps"][0]["run"]
    match = re.search(r"python3 - <<'PYTHON'\n(.*?)\nPYTHON", script, re.DOTALL)
    assert match is not None
    result = subprocess.run(
        [sys.executable, "-c", match.group(1)],
        env={**os.environ, "NEEDS_RESULTS": json.dumps({"test": {"result": status}})},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected
