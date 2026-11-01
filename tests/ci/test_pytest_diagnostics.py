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


def launch(tmp_path, test_source, conftest="", extra_env=None):
    test = tmp_path / "test_probe.py"
    test.write_text(test_source)
    (tmp_path / "conftest.py").write_text(conftest)
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n")
    return launch_command(
        tmp_path,
        [
            sys.executable,
            "-u",
            "-m",
            "scripts.pytest_diagnostics",
            str(test),
            "-c",
            str(config),
            "-q",
        ],
        extra_env,
    )


def launch_command(tmp_path, command, extra_env=None):
    return subprocess.Popen(
        ["bash", str(SHELL), *command],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTEST_DIAGNOSTIC_INTERVAL": "0.2",
            "PYTEST_DIAGNOSTIC_PIDFILE": "",
            "PYTHONPATH": str(ROOT),
            "RUNNER_TEMP": str(tmp_path),
            **(extra_env or {}),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def drain(process, tmp_path, timeout):
    try:
        return process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        print(f"DIAGNOSTIC_TIMEOUT wrapper_alive={process.poll() is None}", flush=True)
        print((error.output or b"")[-16000:].decode(errors="replace"), flush=True)
        groups = {str(process.pid)}
        for path in tmp_path.glob("atelier-pytest.*/command.pid"):
            groups.add(path.read_text().strip())
        try:
            states = subprocess.run(
                ["ps", "-eo", "pid,ppid,pgid,stat,etime,comm"],
                capture_output=True,
                text=True,
                timeout=2,
                check=True,
            )
            for line in states.stdout.splitlines()[1:]:
                fields = line.split()
                if len(fields) >= 3 and fields[2] in groups:
                    print("TIMEOUT_PROCESS_STATE " + line, flush=True)
        except OSError, subprocess.SubprocessError:
            print("TIMEOUT_PROCESS_STATE unavailable", flush=True)
        raise


def finish(process, tmp_path):
    groups = [
        int(path.read_text()) for path in tmp_path.glob("atelier-pytest.*/command.pid")
    ]
    if process.poll() is None:
        process.terminate()
    try:
        process.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        for group in [*groups, process.pid]:
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.communicate(timeout=3)
    if process.stdout:
        process.stdout.close()


@pytest.mark.parametrize("passing,expected", [(True, 0), (False, 1)])
def test_diagnostic_boundary_preserves_exit_codes(tmp_path, passing, expected):
    process = launch(tmp_path, f"def test_probe():\n    assert {passing}\n")
    try:
        output, _ = drain(process, tmp_path, timeout=15)
        text = output.decode()
        assert process.returncode == expected, text
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
signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR2})
def diagnostic_shutdown_blocker():
    signal.sigwait({signal.SIGUSR2})
def test_probe():
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
signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR2})
def diagnostic_phase_blocker():
    signal.sigwait({signal.SIGUSR2})
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
        remainder, _ = drain(process, tmp_path, timeout=10)
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


def test_watchdog_reaps_blocked_process_sampler_and_closes_output(tmp_path):
    import shutil

    fifo = tmp_path / "ready.fifo"
    os.mkfifo(fifo)
    real_ps = shutil.which("ps")
    assert real_ps is not None
    sampler_pid = tmp_path / "sampler.pid"
    sampler = tmp_path / "ps"
    sampler.write_text(f"""#!/usr/bin/env python3
import os,signal,sys
from pathlib import Path
try:
    descriptor=os.open({str(tmp_path / "claimed")!r},os.O_CREAT|os.O_EXCL|os.O_WRONLY)
except FileExistsError:
    os.execv({real_ps!r},[{real_ps!r},*sys.argv[1:]])
os.close(descriptor)
Path({str(sampler_pid)!r}).write_text(str(os.getpid()))
with open({str(fifo)!r},'w') as stream:
    stream.write('x')
signal.pause()
""")
    sampler.chmod(0o755)
    process = launch_command(
        tmp_path,
        [sys.executable, "-c", f"with open({str(fifo)!r}) as stream: stream.read(1)"],
        {"PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]},
    )
    try:
        output, _ = drain(process, tmp_path, timeout=10)
        assert process.returncode == 0, output.decode()
        assert b"command_process_exit code=0" in output
        assert b"shell_step_complete code=0" in output
        # ps was a direct owned child. Successful communicate also establishes EOF.
        with pytest.raises(ProcessLookupError):
            os.kill(int(sampler_pid.read_text()), 0)
    finally:
        if sampler_pid.exists():
            try:
                os.kill(int(sampler_pid.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
        finish(process, tmp_path)


def read_until(process, marker, timeout=10):
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    output = b""
    deadline = time.monotonic() + timeout
    with selector:
        while marker not in output:
            for key, _ in selector.select(timeout=max(0, deadline - time.monotonic())):
                chunk = os.read(key.fd, 65536)
                assert chunk, output.decode()
                output += chunk
            assert time.monotonic() < deadline, output.decode()
    return output


@pytest.mark.parametrize(
    "interruption,expected", [(signal.SIGINT, 130), (signal.SIGTERM, 143)]
)
def test_interruption_reaps_command_and_watchdog(tmp_path, interruption, expected):
    process = launch(
        tmp_path,
        """import select
def diagnostic_interrupt_blocker():
    select.select([], [], [])
def test_probe():
    diagnostic_interrupt_blocker()
""",
    )
    try:
        read_until(process, b"diagnostic_interrupt_blocker")
        process.send_signal(interruption)
        output, _ = drain(process, tmp_path, timeout=10)
        assert process.returncode == expected, output.decode()
        assert f"shell_step_complete code={expected}".encode() in output
        assert b"python_process_exit_observed" in output
    finally:
        finish(process, tmp_path)


def test_timeout_cleanup_terminates_owned_sessions_and_drains_output(tmp_path):
    process = launch(
        tmp_path,
        """import select
def diagnostic_timeout_blocker():
    select.select([], [], [])
def test_probe():
    diagnostic_timeout_blocker()
""",
    )
    try:
        read_until(process, b"diagnostic_timeout_blocker")
        with pytest.raises(subprocess.TimeoutExpired):
            process.communicate(timeout=0.1)
        assert process.poll() is None
        process.terminate()
        output, _ = drain(process, tmp_path, timeout=10)
        assert process.returncode == 143, output.decode()
        assert b"shell_step_complete code=143" in output
    finally:
        finish(process, tmp_path)


def test_orphaned_output_writer_is_removed_and_not_reported_as_success(tmp_path):
    child_pid = tmp_path / "writer.pid"
    command = f"""import subprocess,sys
from pathlib import Path
child=subprocess.Popen([sys.executable,'-c','import signal; signal.pause()'])
Path({str(child_pid)!r}).write_text(str(child.pid))
"""
    process = launch_command(tmp_path, [sys.executable, "-c", command])
    try:
        output, _ = drain(process, tmp_path, timeout=10)
        assert process.returncode == 1, output.decode()
        assert b"remaining_descendants_after_command_exit" in output
        assert b"shell_step_complete code=1" in output
        # A grandchild may briefly be an adopted zombie; it must not be running
        # or retain any output descriptor after its original session owner exits.
        result = subprocess.run(
            ["ps", "-p", child_pid.read_text(), "-o", "stat="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        assert not result.stdout.strip() or result.stdout.strip().startswith("Z")
    finally:
        if child_pid.exists():
            try:
                os.kill(int(child_pid.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
        finish(process, tmp_path)


def test_late_watchdog_signal_is_safe_after_handler_unregistration(tmp_path):
    process = launch(
        tmp_path,
        """import atexit
import faulthandler
import os
import signal
import sys
signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR2})
def diagnostic_late_finalizer():
    faulthandler.unregister(signal.SIGUSR1)
    os.write(sys.modules["__main__"].TRACE_FD, b"LATE_FINALIZER_READY\\n")
    signal.sigwait({signal.SIGUSR2})
def test_probe():
    atexit.register(diagnostic_late_finalizer)
""",
    )
    try:
        output = read_until(process, b"LATE_FINALIZER_READY")
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
        os.kill(pid, signal.SIGUSR1)
        os.kill(pid, signal.SIGUSR2)
        remainder, _ = drain(process, tmp_path, timeout=10)
        assert process.returncode == 0, (output + remainder).decode()
        assert b"shell_step_complete code=0" in remainder
    finally:
        finish(process, tmp_path)
