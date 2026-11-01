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
The initial diagnostics at commit `2aa2a4b` ran in CI run 41292256234. That run
completed with 694 passed and one failing diagnostic subprocess test. Its outer
pytest returned 1, make returned 2, and the shell completed; the original
10-minute timeout did not recur. The lifecycle corrections described below are
local and have not been pushed or run remotely.

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
fail. After reporting them it kills the ended session's remaining process group
to close inherited output pipes; the diagnostic failure remains nonzero.

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
proves the runner observed completion. The watchdog owns `ps`, `awk` and `sleep` as separate direct children, each
started in the background and waited for with an interruptible Bash `wait`. Its
TERM trap requests stopping; normal control flow kills and reaps the active
stateless helper even if termination races with helper creation. No foreground
pipeline can defer the stop trap. The wrapper then waits for the watchdog.
Cancellation signals are forwarded to the command group and the wrapper
re-waits/reaps the command before completing. The launcher resets inherited
SIGINT/SIGTERM dispositions. No additional timeout is imposed on the command.

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

## Initial local result of this instrumentation (before CI run 41292256234)

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

Another CI run **with the lifecycle corrections available in its tested revision** is required.
Do not infer a root cause or apply a cleanup correction until that run supplies
a blocked frame/process observation. GitHub only accepts stored workflow revisions;
the no-commit/no-push constraint prevents running this local revision there.
No uninstrumented rerun was triggered as a substitute.


## Diagnostic subprocess failure: verified lifecycle defects and correction

The CI failure at `communicate(timeout=10)` did not record the nested process's
remaining stack/output in the assertion. The outer job's clean exit establishes
that the original ten-minute job hang was not reproduced. The exact nested wait
in that historical failure cannot be selected retroactively from its logs.
Two defects were reproduced independently; neither requires a slow runner:

1. The synthetic SIGUSR2 handler called `threading.Event.set()` asynchronously.
   Event.wait and Event.set both acquire the same non-reentrant Condition lock.
   Delivering SIGUSR2 while Event.wait held that lock left the monitored Python
   alive, blocked in `threading.Condition.__enter__ -> Event.set -> signal handler
   -> Event.wait`. A native dump verified that wait. The synthetic probes now
   block SIGUSR2 and consume it synchronously with `sigwait`. Signals pending
   before the wait remain pending; no lock-acquiring Python signal handler runs.
2. The old watchdog ran `ps | awk` in the foreground. A FIFO-coordinated sampler
   reproduced a command that had already exited 0 while the wrapper remained in
   watchdog cleanup. Bash deferred the watchdog TERM trap until the sampler
   finished. Terminating that sampler immediately let the wrapper return 0.
   Those helpers also retained inherited output descriptors. The corrected
   watcher tracks, terminates and waits for each direct helper; no pipeline or
   untracked sleep survives cleanup. The regression verifies both EOF and that
   the sampler PID has been reaped.

A further local race produced status 158 (128 + macOS SIGUSR1): a late dump signal
could arrive after faulthandler unregistered its handler during finalization.
SIGUSR1 now has an ignored fallback disposition before faulthandler registration.
Native dumps work while registered; after unregistration a late signal cannot
terminate the interpreter. A controlled atexit test verifies that boundary.

Timeouts have not been increased. If a nested test times out again, `drain`
prints its wrapper state, retained output/stacks and only the owned process-group
identities before cleanup. Test cleanup first requests TERM and drains output;
a bounded three-second fallback kills known owned groups and reaps the wrapper.
This is test-resource cleanup after a failure, not a retry or a larger test deadline.
Interruption probes use an OS select wait, which is interruptible by SIGINT;
synchronous SIGUSR2 coordination is reserved for deliberate release probes.

Regressions cover normal/failing commands, blocked sampler shutdown, fixture and
session finalization, interpreter joining, SIGINT/SIGTERM, caller timeout cleanup,
an orphan holding output open, and late handler unregistration. Process-group
cleanup reports unexpected descendants as failure even after terminating them.
An intentionally orphaned grandchild may briefly be an adopted zombie awaiting
OS reaping, but it is terminated and cannot retain output descriptors. All direct
owned command/watchdog/helper processes are explicitly waited for.

These deterministic reproductions establish real lifecycle faults and validate
the corrections. They do not prove which fault caused the historical CI fixture
timeout or explain the separate original ten-minute incident. Remote validation
of the corrected diagnostics is still required; no commit/push/release is made.


### Verification after lifecycle corrections

- Previously failing `[fixture]` probe: 100 consecutive successful repetitions
  with its existing communicate timeout unchanged.
- `make test-fast`: **701 passed in 24.08s** (all previous 695 retained, six
  additional lifecycle cases).
- Exact wrapped CI command: **701 passed**, actual Python/command/shell exit 0,
  final `python_process_exit_observed` and `shell_step_complete code=0` markers.
- Complete PostgreSQL suite: **1251 passed in 49.41s**, using disposable local
  worker databases, not development/Neon databases.
- Ruff, formatting, mypy, Bash syntax, actionlint and whitespace checks passed.

The blocked sampler regression specifically verifies that its direct child PID
has been reaped and communicate observes EOF. Interrupted and timed-out probes
verify their command and watchdog terminate and drain their inherited streams.
Normal/failed command statuses remain 0/1; signal-driven cancellation is 130/143.
An orphaned output writer is terminated and produces diagnostic failure 1.
The wrapper still retains the original ten-minute CI job limit. No increased
communicate deadline, arbitrary delay or automatic retry is used as a correction.
