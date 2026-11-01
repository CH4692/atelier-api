"""Temporarily trace pytest phases and keep native dumps alive through shutdown."""

import atexit
import faulthandler
import json
import os
import platform
import signal
import sys
import threading
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest

# Own a descriptor independent of pytest's capture/temporary stderr descriptors.
TRACE_FD = os.dup(2)
INTERVAL = float(os.environ.get("PYTEST_DIAGNOSTIC_INTERVAL", "30"))


def mark(phase: str, **details: object) -> None:
    """Flush structured diagnostics without request bodies, URLs or environments."""
    record = {
        "at": datetime.now(UTC).isoformat(),
        "pid": os.getpid(),
        "phase": phase,
        **details,
    }
    os.write(TRACE_FD, ("PYTEST_DIAGNOSTIC " + json.dumps(record) + "\n").encode())


def arm_dumps() -> None:
    """Keep a native watchdog active even after pytest restores its own handlers."""
    faulthandler.enable(file=TRACE_FD, all_threads=True)
    faulthandler.dump_traceback_later(INTERVAL, repeat=True, file=TRACE_FD)


def snapshot(phase: str) -> None:
    """Inspect thread identities and the loaded engine without opening connections."""
    mark(
        phase,
        threads=[
            {"name": thread.name, "ident": thread.ident, "daemon": thread.daemon}
            for thread in threading.enumerate()
        ],
    )
    module = sys.modules.get("atelier_api.database")
    engine = getattr(module, "engine", None)
    if engine is not None:
        mark(
            "database_pool",
            backend=engine.dialect.name,
            pool=type(engine.pool).__name__,
            state=engine.pool.status(),
            postgres_query="not performed; diagnostics never open database connections",
        )


class PhaseProbe:
    """Observe existing hooks without changing selection, fixtures or exit codes."""

    def pytest_configure(self, config: pytest.Config) -> None:
        mark(
            "pytest_configured",
            capture=config.getoption("capture"),
            plugins=[
                {"name": dist.project_name, "version": dist.version}
                for _, dist in config.pluginmanager.list_plugin_distinfo()
            ],
        )

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtestloop(self) -> Generator[None, object, object]:
        mark("test_execution_begin")
        result = yield
        snapshot("test_execution_complete")
        return result

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_teardown(
        self, nextitem: pytest.Item | None
    ) -> Generator[None, object, object]:
        if nextitem is None:
            snapshot("last_fixture_teardown_begin")
        result = yield
        if nextitem is None:
            snapshot("last_fixture_teardown_complete")
        return result

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_sessionfinish(self, exitstatus: int) -> Generator[None, object, object]:
        arm_dumps()
        snapshot("session_finalization_begin")
        result = yield
        snapshot("session_finalization_complete")
        mark("pytest_session_exit_status", code=int(exitstatus))
        return result

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_terminal_summary(self) -> Generator[None, object, object]:
        mark("terminal_summary_begin")
        result = yield
        mark("terminal_summary_complete")
        return result

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_unconfigure(self) -> Generator[None, object, object]:
        snapshot("pytest_unconfigure_begin")
        result = yield
        arm_dumps()
        snapshot("pytest_unconfigure_complete")
        return result


def main() -> int:
    """Run pytest with unchanged arguments; shell wait establishes actual exit."""
    mark(
        "python_process_start",
        python=platform.python_version(),
        system=platform.system(),
        parent=os.getppid(),
    )
    arm_dumps()
    faulthandler.register(signal.SIGUSR1, file=TRACE_FD, all_threads=True)
    pidfile = os.environ.get("PYTEST_DIAGNOSTIC_PIDFILE")
    if pidfile:
        stat = Path(f"/proc/{os.getpid()}/stat")
        token = (
            stat.read_text().partition(") ")[2].split()[19] if stat.exists() else "-"
        )
        ready = Path(pidfile + ".ready")
        ready.write_text(f"{os.getpid()} {token}\n")
        ready.replace(pidfile)
    # Thread joining precedes atexit; native timer and shell SIGUSR1 stay active
    # until the OS closes the process, including after this final atexit marker.
    atexit.register(snapshot, "python_atexit_reached")
    mark("pytest_call_begin")
    try:
        code = int(pytest.main(sys.argv[1:], plugins=[PhaseProbe()]))
    finally:
        arm_dumps()
    mark("pytest_return", code=code)
    snapshot("python_shutdown_begin")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
