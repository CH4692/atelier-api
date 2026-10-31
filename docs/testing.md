# Testing and required CI

## Strategy and categories

`make test` is the complete offline automated suite and requires PostgreSQL. Fast
feedback is deliberately separate from complete verification. Production password
hashing/verification, session security, role checks, CSRF, foreign keys and all
existing assertions remain intact. No tests are removed, xfailed or retried to
conceal failures. Real R2 credentials are never inherited by normal tests.

The existing directory layout is retained. The collection hook classifies tests
under `tests/integration` as `integration`; lightweight HTTP tests using `client`
and the existing application/multipart modules are `api`; other isolated tests
are `unit`. Critical existing workflows additionally carry `e2e` (a subset of
integration, not a second duplicate execution). Unit/API jobs also include the
existing deterministic CLI, Git and release-build regression tests.

| Category | Scope / dependencies | Selection |
|---|---|---|
| Unit | Validation, rules, transformations, isolated CLI/tooling | `-m unit` |
| API | Lightweight HTTP contracts with mocked persistence | `-m api` |
| Integration | Real PostgreSQL, API/services, constraints, audit, transactions | `tests/integration` |
| E2E workflow | Authenticated API business workflows and the operational purge/storage lifecycle | `-m e2e` |
| External smoke | Deployed API or real R2 development bucket | Manual only; none currently supplied |

E2E here means in-process application workflows with real PostgreSQL and fake
private storage, not browser/Render/real-R2 verification. The instrument lifecycle
now logs in as an employee rather than bypassing authorization. Existing legacy
persistence tests retain their explicit auth override; dedicated authentication,
RBAC/CSRF tests and the authenticated workflows do not bypass those checks.

## Local commands

After `uv sync --locked --dev`:

| Command | Meaning |
|---|---|
| `make test-fast` | All non-PostgreSQL tests; never complete verification |
| `make test-integration` | Every PostgreSQL integration test, including E2E |
| `make test-e2e` | Critical workflow subset, including auth/repair/photo/retention/purge |
| `make test` | Entire suite, with required PostgreSQL |
| `make check` | Ruff lint, format check and mypy |
| `make test-integration TEST_WORKERS=2` | Isolated two-worker PostgreSQL run |
| `make test PYTEST_ARGS='-n 2 --dist=loadfile'` | Entire suite with two workers |
| `make test PYTEST_ARGS='--durations=50 --durations-min=0.1'` | Profile slow phases |

The serial default (`TEST_WORKERS=0`) preserves operation with a restricted remote
test role. CI uses two workers, conservatively limiting database/Argon2 resource
pressure; four-worker measurements are documented but not blindly applied to all
runner sizes. Avoid `-n auto` on small machines. Use `--dist=loadfile` to keep each
module together. All supported worker counts preserve constraints and real
transaction/concurrency tests.

`--require-postgres`, used by complete/integration/E2E Make targets, fails early
if TEST_DATABASE_URL is missing. An invalid/unreachable configured database fails;
there is no SQLite integration fallback. Direct `uv run pytest` keeps the legacy
missing-database skip behavior for interactive use, so it is not proof of complete
verification without checking the skip summary. CI always requires PostgreSQL.

## PostgreSQL setup and isolation

Prefer a disposable local PostgreSQL server over remote round trips. For example:

```bash
docker run --name atelier-tests --rm \
  -e POSTGRES_USER=atelier -e POSTGRES_PASSWORD=atelier_test \
  -e POSTGRES_DB=atelier_test -p 127.0.0.1:55432:5432 postgres:17
```

In a second shell, configure only the dedicated disposable test database:

```bash
export DATABASE_URL='postgresql+psycopg://atelier:atelier_test@127.0.0.1:55432/atelier_test'
export TEST_DATABASE_URL="$DATABASE_URL"
make test
```

These are disposable example credentials. Never point tests at production or a
shared application database. Database names must end in `_test`. Serial mode needs
schema create/drop privileges. Parallel mode additionally needs CREATEDB on this
disposable test server; it fails clearly rather than sharing a database or falling
back. Do not grant additional privileges to production/ordinary Neon roles just
for tests—use local/CI PostgreSQL or serial testing instead.

Each serial session migrates a UUID-named schema once. Ordinary tests bind all API
sessions to an outer transaction using `join_transaction_mode=create_savepoint`.
Application commits release savepoints; teardown rolls back the outer transaction.
One SELECT then checks every existing table and the bootstrap latch, preserving
all eleven prior validations with ten fewer round trips per test. An independent
connection regression test verifies that an application commit is not externally
visible. Immutable full-strength fixture password hashes are reused per session;
real login verification and dedicated salt/cost compatibility tests remain intact.

Each xdist worker creates a separate random database such as
`atelier_gw0_a1b2c3d4_test`, with UTC defaults, on the explicitly configured test
server. Its migrated schema and mutable rows are not shared with other workers.
UTC connection settings avoid inheriting a workstation's cluster timezone. A
UUID suffix avoids collisions with concurrent runs. The worker disposes connections
and drops only its own database on exit; interrupted/force-killed runs can leave
recognizable test databases for reviewed operator cleanup. Never broadly drop a
database prefix on a shared server. Worker DB creation never touches the base
schema/data. No database state is cached across jobs.

Real-commit/concurrency tests intentionally use independent connections and
explicit fixture cleanup, not an assumption that an outer transaction covers all
connections. Migration upgrade tests use separate disposable schemas. New tests
opening connections/CLI sessions must use the fixture's `postgres_engine` (or
explicitly override the CLI engine), not the application/development global engine.
Rollback checks detect leaked committed data. Advisory locks are database-wide;
worker schemas alone would not isolate purge tests, which is why databases are
separate.

## CI and required checks

Workflow name **Attelier CI** remains unchanged so the existing privileged release
workflow keeps its guarded `workflow_run` dependency. CI runs on every PR targeting
main, every push to main, and merge-queue check requests. No path filters omit
verification. Only obsolete PR runs are cancelled; main verification is retained.

Independent jobs run in parallel with read-only repository permissions, no R2
secrets, uv dependency caching and bounded timeouts:

| Exact GitHub status check name | Required coverage |
|---|---|
| `lint` | Ruff and format check |
| `typecheck` | mypy |
| `Unit and API tests` | All non-PostgreSQL tests |
| `test` | Every PostgreSQL integration test and all marked E2E workflows |
| `Database Migrations` | Empty PostgreSQL 17, upgrade head, Alembic consistency, supported downgrade/upgrade round trip |
| `Wheel installation` | uv build, clean installation, imports/API metadata and CLI entry points outside the checkout |
| `Required CI` | All six jobs must succeed; failure, cancellation or skip fails the aggregate gate |

The existing `test`, `lint`, `typecheck`, `Database Migrations` and `Wheel installation`
status names are preserved. Integration/E2E are executed exactly once in normal CI;
the optional local E2E command is not a duplicate CI job. The PostgreSQL service
has readiness health checks and disposable non-production credentials. Session
fixtures apply all migrations to the actual worker databases; `create_all()` is
never substituted. The migration job separately tests an empty database and the
latest supported round trip. Data-preserving migrations/downgrade safeguards remain
covered in integration tests. Pytest exit codes are never ignored and required
jobs do not use continue-on-error.

Critical regression coverage includes instrument/customer CRUD and associations,
protected instrument deletion/FKs, repair chronology/documents, photo upload,
view/download, restoration/holds/permanent purge and failure recovery, login/logout,
expiry, roles, CSRF, rate limits, plus successful/rolled-back audit events. The
existing instrument deletion tests in `test_instrument_api.py`, `test_instruments.py`,
`test_workshop_history.py` and photo tests are all included by directory selection.
New tests in that directory automatically become mandatory.

### Manual GitHub settings

Workflow files alone cannot require checks before merging. No remote protection
settings were changed or verified by this work. In Settings → Rules → Rulesets
(or branch protection), target `main` and:

1. Require a pull request before merging.
2. Require the seven exact status check names in the table above, from GitHub
   Actions. `Required CI` alone also aggregates all coverage, but preserve existing
   individual requirements and add the new checks explicitly during rollout.
3. Require branches to be up to date, or configure Merge Queue (merge_group is
   supported). Ensure checks are required for the relevant merge revision.
4. Restrict bypass actors to approved release automation. Review bypass policy;
   bypass capability is not evidence that generated changes passed CI.
5. Run a PR once to register the new status names, then configure them. Verify
   that an intentional integration failure prevents merging before relying on it.

Release permissions, GitHub App credentials, version/tag behavior and release
workflow are unchanged. Untrusted PR code never receives release credentials;
CI does not use pull_request_target or a privileged report-publishing workflow.

## Diagnostics, privacy and reliability

Both test jobs print collection/results and slowest-phase diagnostics, create
JUnit XML even on test failure, and append counts/timings/failure identities to
the GitHub job summary. Only sanitized JUnit is uploaded for seven days. Captured
output, XML properties, raw tracebacks and parameter values are removed; hashed
case IDs preserve distinctions. Failure details remain in the short pytest console
traceback. Do not enable --showlocals or SDK wire logging, and never put real
credentials into test parametrization. No report reads secrets from external apps.

Two worker collection defects were found and corrected: random QR IDs and random
unknown session tokens in parametrization. QR lookup uses a stable nonexistent
UUID; token tests retain random token values but stable descriptive case IDs.
Runtime object IDs and salts remain random where their uniqueness is tested.
Existing Event-based concurrency synchronization and deterministic expiration
clocks remain; there are no sleep-based expiry tests to remove. No automatic
reruns hide flakiness. Parallel CI must not split mutable fixtures across threads
inside one process; xdist uses independent processes/databases.

Normal tests use fake storage and boto3 Stubber, never real R2. No destructive
external smoke test is added or scheduled. Real deployment/R2 checks remain a
separate, explicitly authorized development-bucket procedure; never give production
storage credentials to PR workflows.

Troubleshooting:

- Missing TEST_DATABASE_URL: use the dedicated DB setup above; complete commands
  intentionally fail instead of reporting success with skipped integration tests.
- CREATEDB denied: use `TEST_WORKERS=0` or provision a disposable local/CI server.
- UTC failures: inspect test connection options, not production timestamp semantics.
- Worker collection mismatch: give runtime-generated parameters stable IDs; never
  delete the failing cases.
- Leaked rows: inspect additional connections/real commits and their fixture cleanup.
- Slow remote runs: compare `--durations`, setup/teardown and SQL round trips before
  changing security costs. Prefer local disposable PostgreSQL for development.
- Failed/skipped CI dependency: `Required CI` must fail; never mark it optional or
  hide pytest exit codes. Inspect sanitized case identities and console details.

Local measured before/after results and limitations are in
[testing-performance.md](testing-performance.md). GitHub wall-clock runtime cannot
be measured without an actual remote run; no push, workflow trigger or release is
performed merely to obtain a benchmark.

Reference: [pytest-xdist worker identifiers and isolation](https://pytest-xdist.readthedocs.io/en/stable/how-to.html),
[GitHub workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax),
and [pytest reporting](https://docs.pytest.org/en/stable/how-to/output.html).
