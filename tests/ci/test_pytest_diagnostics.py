"""Verify the temporary watchdog across failures and interpreter thread joining."""

import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "scripts/diagnose_pytest.sh"


def launch(tmp_path, test_source, conftest=""):
    test = tmp_path / "test_probe.py"
    test.write_text(test_source)
    (tmp_path / "conftest.py").write_text(conftest)
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n")
    return subprocess.Popen(
        [
            "bash",
            str(SHELL),
            sys.executable,
            "-u",
            "-m",
            "scripts.pytest_diagnostics",
            str(test),
            "-c",
            str(config),
            "-q",
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTEST_DIAGNOSTIC_INTERVAL": "0.2",
            "PYTEST_DIAGNOSTIC_PIDFILE": "",
            "PYTHONPATH": str(ROOT),
            "RUNNER_TEMP": str(tmp_path),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def finish(process, tmp_path):
    for pidfile in tmp_path.glob("atelier-pytest.*/python.pid"):
        pid = int(pidfile.read_text().split()[0])
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=5)
    if process.stdout:
        process.stdout.close()


@pytest.mark.parametrize("passing,expected", [(True, 0), (False, 1)])
def test_diagnostic_boundary_preserves_exit_codes(tmp_path, passing, expected):
    process = launch(tmp_path, f"def test_probe():\n    assert {passing}\n")
    try:
        output, _ = process.communicate(timeout=15)
        text = output.decode()
        assert process.returncode == expected
        for marker in [
            "python_process_start",
            "last_fixture_teardown_complete",
            "test_execution_complete",
            "session_finalization_complete",
            "terminal_summary_complete",
            "pytest_return",
            "python_atexit_reached",
            "python_process_exit_observed",
            f"shell_step_complete code={expected}",
        ]:
            assert marker in text
        assert f'"phase": "pytest_return", "code": {expected}' in text
        assert "remaining_descendants_after_command_exit" not in text
    finally:
        finish(process, tmp_path)


@pytest.mark.parametrize("stage", ["fixture", "session", "interpreter"])
def test_native_dumps_and_watchdog_cover_finalization_and_shutdown(tmp_path, stage):
    if stage == "interpreter":
        test = """import signal
import threading
release = threading.Event()
def diagnostic_shutdown_blocker():
    release.wait()
def test_probe():
    signal.signal(signal.SIGUSR2, lambda *_: release.set())
    threading.Thread(target=diagnostic_shutdown_blocker, name="shutdown-probe").start()
"""
        conftest = ""
        marker = b'"phase": "python_shutdown_begin"'
        frame = b"diagnostic_shutdown_blocker"
    else:
        test = "def test_probe(): pass\n"
        conftest = """import signal
import threading
import pytest
release = threading.Event()
signal.signal(signal.SIGUSR2, lambda *_: release.set())
def diagnostic_phase_blocker():
    release.wait()
"""
        if stage == "fixture":
            conftest += """@pytest.fixture(autouse=True)
def held_fixture():
    yield
    diagnostic_phase_blocker()
"""
            marker = b'"phase": "last_fixture_teardown_begin"'
        else:
            conftest += "def pytest_sessionfinish(): diagnostic_phase_blocker()\n"
            marker = b'"phase": "session_finalization_begin"'
        frame = b"diagnostic_phase_blocker"
    process = launch(tmp_path, test, conftest)
    try:
        assert process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        output = b""
        deadline = time.monotonic() + 15
        with selector:
            while time.monotonic() < deadline:
                for key, _ in selector.select(
                    timeout=max(0, deadline - time.monotonic())
                ):
                    chunk = os.read(key.fd, 65536)
                    assert chunk, output.decode()
                    output += chunk
                if marker in output and frame in output.split(marker)[-1]:
                    break
            else:
                pytest.fail(output.decode())
        assert b'"phase": "python_atexit_reached"' not in output
        import json

        records = [
            json.loads(line.split("PYTEST_DIAGNOSTIC ", 1)[1])
            for line in output.decode().splitlines()
            if line.startswith("PYTEST_DIAGNOSTIC ")
        ]
        pid = next(
            record["pid"]
            for record in records
            if record["phase"] == "python_process_start"
        )
        os.kill(pid, signal.SIGUSR2)
        remainder, _ = process.communicate(timeout=10)
        assert process.returncode == 0
        assert b"shell_step_complete code=0" in remainder
        assert b"python_atexit_reached" in remainder
        assert b"watchdog command_pid=" in output + remainder
    finally:
        finish(process, tmp_path)


def test_ci_enables_temporary_diagnostics_without_changing_test_selection():
    from tests.ci.test_ci_policy import workflow

    job = workflow()["jobs"]["unit-api"]
    assert job["timeout-minutes"] == "10"
    command = next(
        step["run"]
        for step in job["steps"]
        if step.get("name") == "Run unit and lightweight API tests"
    )
    assert (
        command
        == 'bash scripts/diagnose_pytest.sh make test-fast PYTEST_ARGS="--durations=20 --tb=short --junitxml=reports/unit-api.raw.xml"'
    )
    recipe = (
        (ROOT / "Makefile").read_text().split("test-fast:\n", 1)[1].split("\n\n", 1)[0]
    )
    assert '--ignore=tests/integration -m "not external" $(PYTEST_ARGS)' in recipe
    assert "PYTEST ?= pytest" in (ROOT / "Makefile").read_text()
