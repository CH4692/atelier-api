# Temporary pytest shutdown diagnostics

## Evidence and limits

Run 41278232712 and its unchanged debug rerun timed out in `unit-api`. GitHub's
annotation explicitly reported the 10-minute execution limit. The following
sanitization/upload steps had not begun. The original unit/API logs were missing
from the downloaded run archive; no blocking Python stack is available from it.
Concurrency cancellation, a runner disconnect and a particular fixture/plugin
have not been established as the underlying cause.

The unmodified fast command passed all 689 existing cases on macOS with Python
3.14.3 and 3.14.8 and on Linux x86_64 with Python 3.14.8. Each printed the final
summary and exited 0. The Linux run used Debian bookworm under QEMU rather than
the GitHub Ubuntu image. Local hook probes showed only MainThread remaining;
that observation cannot establish the remote runner's state.

This change instruments the failure; it does not claim to fix its unknown cause.
The diagnostic workflow has not been run remotely: uncommitted local workflow
changes cannot be executed by GitHub Actions. Re-running an existing revision
would not exercise this instrumentation. No commit, push or release is performed.

## Commands and environment

The original command is unchanged inside the diagnostic shell wrapper:

```sh
bash scripts/diagnose_pytest.sh make test-fast PYTEST_ARGS="--durations=20 --tb=short --junitxml=reports/unit-api.raw.xml"
```

The wrapper sets the optional Make variable `PYTEST` to
`python -u -m scripts.pytest_diagnostics`. Its default remains `pytest` for normal
runs. The effective diagnostic invocation is:

```sh
uv run python -u -m scripts.pytest_diagnostics --ignore=tests/integration -m "not external" --durations=20 --tb=short --junitxml=reports/unit-api.raw.xml
```

`pytest.main` receives the same test-selection/reporting arguments. Every original
test remains selected; the diagnostic regression tests are additional cases.
The wrapper enables `PYTHONUNBUFFERED=1` and `PYTHONFAULTHANDLER=1`. The CI job's
existing `timeout-minutes: 10`, permissions, services and required-job gate remain
unchanged. The interval is 30 seconds; it schedules diagnostic observation, not
a retry or forced termination. A dump may occur during normal slow progress too.

The original CI shell uses Bash with fail-on-error. The wrapper records the
command's exit status and returns it, without `continue-on-error`, `|| true` on
tests, forced success, or changing assertions. Active descendant processes after
the command exits are reported and make an otherwise successful diagnostic step
fail. It does not silently kill those descendants to manufacture success.

## Markers and boundary coverage

`PYTEST_DIAGNOSTIC` records have UTC timestamps, process IDs and phase names:

1. `python_process_start` and `pytest_call_begin`.
2. `test_execution_begin`.
3. `last_fixture_teardown_begin` / `last_fixture_teardown_complete`. Session-scoped
   fixture finalizers normally run as part of the last item's teardown.
4. `test_execution_complete` (the runtest loop, including teardown, returned).
5. `session_finalization_begin` / `session_finalization_complete`, with nested
   `terminal_summary_begin` / `terminal_summary_complete`.
6. `pytest_unconfigure_begin` / `pytest_unconfigure_complete`.
7. `pytest_return` with the actual return code and `python_shutdown_begin`.
8. `python_atexit_reached` after non-daemon thread joining. It does **not** prove
   that later atexit callbacks, C cleanup or the OS process have finished.

An independent Bash watchdog emits `SHELL_DIAGNOSTIC` heartbeats and process names,
PIDs, PPIDs, process groups, state and elapsed time. It signals the recorded
interpreter with SIGUSR1 for native all-thread stacks. Linux process-start ticks
prevent signalling a recycled PID. The PID file is published atomically only
once the signal handler is installed. A native faulthandler timer also repeats
through execution, teardown, pytest finalization and interpreter shutdown. Its
stderr descriptor is independent of pytest capture. Pytest can cancel its own
watchdog in error paths; the shell signal path remains independent. After pytest
returns, the native timer is explicitly rearmed and stays active through atexit.

The command runs in its own process group so descendants can still be identified
after reparenting. Shell observations distinguish `command_process_exit`,
`python_process_exit_observed`, `python_process_still_present`, and
`remaining_descendants_after_command_exit`. `shell_step_complete` records the
wrapper's final statement and code; only GitHub's completed step/next-step state
proves the runner observed completion. The diagnostic watchdog's own sleep
process is terminated and reaped at cleanup. Cancellation signals are forwarded
to the command group; no additional timeout is imposed on the tested application.

## Threads, processes and database privacy

Snapshots show thread names/IDs/daemon flags, plugin versions, Python version,
platform, capture mode and the already-loaded application's pool status. They do
not print environment dumps, process arguments, database URLs, SQL, credentials,
request bodies or frame locals. Native stacks contain filenames/functions/lines.
Diagnostics stay in console output and are not added to uploaded JUnit artifacts.

`unit-api` has DATABASE_URL=sqlite:// and no PostgreSQL service or integration
fixtures. Its PostgreSQL activity is therefore not applicable. The probe never
opens a database connection just to inspect activity, including locally where
.env may contain Neon credentials. Pool state describes only the loaded engine;
it is not a server-wide pg_stat_activity snapshot. If remote output unexpectedly
shows a PostgreSQL backend, investigate that environment difference before
connecting to any server.

Integration runs have a separate disposable PostgreSQL 17 service, explicit
_test URLs and two xdist worker databases. Their fixtures roll back scoped
transactions, verify empty tables, dispose engines and drop worker databases.
The fast job does not enable xdist workers and ignores tests/integration. TestClient
and storage fixtures close clients with context managers/finally. Release/build
subprocesses run in disposable Git repositories and disable remote releases.
None of this lifecycle logic is changed by the diagnostics.

## Reading a failed run

Use the last *completed* marker together with repeated stack frames, process state
and GitHub job/runner diagnostics:

- No runtest completion: inspect the current test/teardown frames. The native
  timer covers fixture teardown too; do not assume 100% means teardown finished.
- Last teardown begins without completing: inspect fixture cleanup frames.
- Runtest loop complete but finalization incomplete: inspect session/plugin hooks.
- pytest returned but atexit is not reached: inspect threading `_shutdown`/join
  and remaining non-daemon threads.
- Atexit reached but process still present: inspect later exit callbacks/native
  teardown. Atexit is not the OS exit boundary.
- Command exited with descendants: inspect reported process groups and their
  inherited streams; do not infer that an orphan blocks output solely from PID.
- Python and command exited but wrapper did not finish: inspect shell cleanup.
- Wrapper completed but GitHub does not acknowledge the step: examine runner
  communication/output handling. Missing output alone does not prove runner loss.

Only a stack/process observation identifying the actual wait supports a root-cause
fix. Another instrumented CI run is required. Keep the 10-minute deadline and all
tests; fix only the demonstrated owner of the blocked resource, then remove this
temporary wrapper, optional Make override, workflow prefix and regression probes.

## Verified local result of this instrumentation

The exact wrapped fast command completed with **695 passed in 20.42s**: the
original 689 cases plus six diagnostic regressions. The final observed sequence
was `terminal_summary_complete`, `session_finalization_complete`,
`pytest_unconfigure_complete`, `pytest_return` code 0, `python_shutdown_begin`,
`python_atexit_reached`, `command_process_exit code=0`,
`python_process_exit_observed`, and `shell_step_complete code=0`.

Only Python MainThread remained in the snapshots (the native faulthandler
watchdog is intentionally active until interpreter exit). The loaded SQLite
SingletonThreadPool reported size 0. No residual process group was reported.
This establishes local completion, not the unknown remote blocking operation.
Full-suite verification passed **1245 tests** using isolated local PostgreSQL
worker databases. Ruff, formatting, mypy, Bash syntax and actionlint passed.

Synthetic blocked fixture teardown, blocked session finalization and a
non-daemon thread blocking interpreter shutdown each produced native stack dumps
*after* their corresponding phase marker. They were then released by an explicit
test signal and exited normally. A deliberately failing synthetic pytest run
preserved exit code 1. These prove diagnostic coverage; their synthetic stacks
are not evidence of the production CI root cause.

Files changed for this temporary investigation:

- `.github/workflows/ci.yaml`: prefix only the unit/API command with the wrapper.
- `Makefile`: optional PYTEST command override for the fast target only.
- `scripts/diagnose_pytest.sh`: independent watchdog and process boundary markers.
- `scripts/pytest_diagnostics.py`: phase probes and native stack dumping.
- `tests/ci/test_pytest_diagnostics.py`: failure propagation, phase-blocking and
  workflow invariants.
- `docs/pytest-shutdown-diagnostics.md`: evidence, usage, interpretation and limits.

Another CI run **with these files available in its tested revision** is required.
Do not infer a root cause or apply a cleanup correction until that run supplies
a blocked frame/process observation. GitHub only accepts stored workflow revisions;
the no-commit/no-push constraint prevents running this local revision there.
No uninstrumented rerun was triggered as a substitute.
