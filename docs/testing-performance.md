# Test performance measurements

## Baseline recorded before optimization

Measured on 2026-10-31 with Python 3.14.3, macOS and isolated local PostgreSQL
16.14 over a Unix socket. No Neon or real R2 service was used. The supplied
37–40 minute environment could not be reproduced; this is a local baseline,
not a claim about historical or GitHub Actions runtime.

Command: `pytest --durations=50 --durations-min=0.1 -q --tb=short` with a temporary
profiling plugin counting phase durations and SQL statements without parameters.

| Metric | Baseline |
|---|---:|
| Collected / passed | 912 / 912 |
| pytest reported duration | 43.13 s |
| Collection (after session start) | 0.90 s |
| Fixture setup (sum) | 11.77 s |
| Test calls (sum) | 29.15 s |
| Fixture teardown (sum) | 0.72 s |
| Successful SQL statements in parent process | 17834 |
| SQL execution time (parent process) | 1.48 s |
| Workers | 0 (serial) |
| GitHub Actions wall time | Not measured; no remote run triggered |

The database already migrates one schema per test session and rolls back ordinary
API tests through savepoints. It does not recreate the schema per test. Real-commit,
concurrency and migration-round-trip tests deliberately use separate transactions
or disposable schemas. Preserve these boundaries.

The cleanup fixture performs eleven separate validation SELECTs per database test.
Combining them preserves all checks while removing ten network round trips per
fixture use. Network latency could amplify this cost on a remote database, but was
not measured against the historical environment. There are no sleep-based expiry
tests to remove. Password fixtures already reuse full-strength Argon2id hashes per
module; session-scope reuse is safe for their immutable common test credential.
Real password verification and security-specific hashing tests must remain intact.
Release-build subprocess tests and the retention migration round trip dominate
the slowest individual calls; they are retained because they verify real behavior.

The slowest 50 setup/call/teardown phases reported by pytest:

```text
2.85s call     tests/integration/test_photo_purge.py::test_retention_migration_preserves_data_and_guards_holds
2.77s call     tests/atelier_api/test_release_build.py::test_pretag_build_tag_checkout_and_gitless_source_archive_agree
0.88s call     tests/atelier_api/test_release_build.py::test_first_release_and_repeated_release_are_safe
0.66s call     tests/atelier_api/test_release_build.py::test_semantic_release_tags_original_commit_without_branch_changes[fix: correct lookup-0.1.1]
0.63s setup    tests/integration/test_audit.py::test_audit_migration_has_independent_ids_indexes_and_timezone
0.62s call     tests/atelier_api/test_release_build.py::test_semantic_release_tags_original_commit_without_branch_changes[feat!: replace contract-0.2.0]
0.61s call     tests/atelier_api/test_release_build.py::test_semantic_release_tags_original_commit_without_branch_changes[fix: replace contract\n\nBREAKING CHANGE: incompatible response-0.2.0]
0.61s call     tests/atelier_api/test_release_build.py::test_semantic_release_tags_original_commit_without_branch_changes[feat: introduce archive-0.2.0]
0.54s call     tests/atelier_api/test_release_build.py::test_semantic_release_tags_original_commit_without_branch_changes[docs: improve instructions-0.1.0]
0.48s call     tests/atelier_api/test_release_configuration.py::test_release_build_stops_if_tool_installation_fails
0.48s call     tests/atelier_api/test_release_build.py::test_semantic_release_tags_original_commit_without_branch_changes[refactor: simplify code-0.1.0]
0.48s call     tests/atelier_api/test_release_build.py::test_semantic_release_tags_original_commit_without_branch_changes[chore: maintenance-0.1.0]
0.48s call     tests/atelier_api/test_release_build.py::test_semantic_release_tags_original_commit_without_branch_changes[test: cover edge case-0.1.0]
0.46s call     tests/atelier_api/test_release_build.py::test_semantic_release_tags_original_commit_without_branch_changes[ci: improve validation-0.1.0]
0.42s call     tests/migrations/test_configuration.py::test_online_connection_failure_is_actionable_and_hides_credentials
0.41s call     tests/migrations/test_configuration.py::test_offline_postgresql_sql_uses_environment_without_connecting
0.21s setup    tests/atelier_api/test_release_build.py::test_semantic_release_tags_original_commit_without_branch_changes[docs: improve instructions-0.1.0]
0.19s setup    tests/atelier_api/test_release_build.py::test_semantic_release_tags_original_commit_without_branch_changes[fix: correct lookup-0.1.1]
0.18s setup    tests/atelier_api/test_release_build.py::test_first_release_and_repeated_release_are_safe
0.18s setup    tests/atelier_api/test_release_build.py::test_semantic_release_tags_original_commit_without_branch_changes[ci: improve validation-0.1.0]
0.18s setup    tests/atelier_api/test_release_build.py::test_semantic_release_tags_original_commit_without_branch_changes[test: cover edge case-0.1.0]
0.18s setup    tests/atelier_api/test_release_build.py::test_semantic_release_tags_original_commit_without_branch_changes[fix: replace contract\n\nBREAKING CHANGE: incompatible response-0.2.0]
0.18s setup    tests/atelier_api/test_release_build.py::test_semantic_release_tags_original_commit_without_branch_changes[feat: introduce archive-0.2.0]
0.18s setup    tests/atelier_api/test_release_build.py::test_semantic_release_tags_original_commit_without_branch_changes[refactor: simplify code-0.1.0]
0.18s setup    tests/atelier_api/test_release_build.py::test_semantic_release_tags_original_commit_without_branch_changes[chore: maintenance-0.1.0]
0.18s setup    tests/atelier_api/test_release_build.py::test_pretag_build_tag_checkout_and_gitless_source_archive_agree
0.18s setup    tests/atelier_api/test_release_build.py::test_semantic_release_tags_original_commit_without_branch_changes[feat!: replace contract-0.2.0]
0.17s call     tests/atelier_api/test_main.py::test_swagger_interceptor_preserves_requests_and_defaults_missing_method_to_get
0.16s call     tests/integration/test_audit.py::test_authentication_records_facts_without_passwords_or_cookie_verifiers
0.16s call     tests/integration/test_users.py::test_concurrent_deactivation_keeps_one_active_administrator
0.15s call     tests/integration/test_auth.py::test_account_rate_limit_is_shared_between_app_instances
0.15s call     tests/integration/test_users.py::test_customer_association_is_explicit_unique_and_does_not_enable_portal
0.15s call     tests/integration/test_audit.py::test_bootstrap_and_deleted_actor_keep_historical_accountability
0.15s call     tests/integration/test_users.py::test_deactivation_revokes_old_identity_and_reactivation_does_not_restore_it
0.14s call     tests/integration/test_users.py::test_role_changes_revoke_existing_identity
0.14s setup    tests/integration/test_photo_retention.py::test_missing_and_unavailable_storage_never_restores
0.14s call     tests/integration/test_auth.py::test_rate_window_resets_and_cleanup_removes_revoked_sessions
0.14s setup    tests/integration/test_workshop_history.py::test_history_is_chronological_and_preserves_documents_after_archiving
0.14s call     tests/users/test_passwords.py::test_same_password_uses_different_random_salts
0.13s setup    tests/integration/test_instrument_ownership.py::test_customer_deletion_keeps_category_and_records_previous_owner
0.13s call     tests/atelier_api/test_release_guard.py::test_main_advancing_after_checkout_blocks_release
0.13s setup    tests/integration/test_instrument_photos.py::test_photo_upload_and_private_retrieval[JPEG-image/jpeg]
0.13s setup    tests/integration/test_photo_retention.py::test_restore_makes_deleted_photo_visible_and_audits
0.12s setup    tests/integration/test_workshop_history.py::test_audit_failure_rolls_back_repair_and_document[document]
0.12s call     tests/integration/test_instrument_photos.py::test_photo_access_rules[employee-404-/1]
0.12s call     tests/integration/test_instrument_qr.py::test_qr_target_is_stable_and_host_headers_are_ignored
0.12s call     tests/integration/test_auth.py::test_rotation_and_logout_prevent_replay
0.12s setup    tests/integration/test_instrument_ownership.py::test_ownership_transfer_retains_former_owners_and_actor
0.12s setup    tests/atelier_api/test_release_guard.py::test_successful_main_push_allows_legitimate_changes[owner]
0.12s call     tests/integration/test_auth.py::test_unsafe_requests_require_origin_and_custom_header[headers4-/api/v1/auth/logout]
```

## Results after optimization

Same local host and PostgreSQL instance. These are individual warm local runs,
not a statistical performance guarantee for GitHub-hosted runners or remote Neon.
All original 912 cases remain collected (parameter labels were stabilized); 20 new
CI-policy/report-privacy/database-isolation tests bring the final total to 932.
No production application or password-security settings were changed.

| Metric | Before | After |
|---|---:|---:|
| Collected tests | 912 | 932 (all original cases retained) |
| Full suite, serial (controlled fixture comparison, original 912 cases) | 43.13 s | 42.13 s |
| Full suite, two workers, final 932 cases | Not measured | 30.97 s |
| Integration suite, serial, 374 cases | Not separately measured | 26.89 s |
| Integration suite, two workers, 374 cases | Not measured | 18.12 s |
| Integration suite, four workers, 374 cases | Not measured | 15.07 s |
| Fast unit/API/tooling suite, 558 cases | Not separately measured | 18.19 s |
| E2E workflow subset, 10 cases | Not separately measured | 1.98 s |
| Slowest full-suite call | 2.85 s (migration round trip) | 3.25 s (same migration round trip, concurrent load) |
| SELECTs, controlled original-suite profiling | 7,929 | 4,509 |
| Setup / call / teardown, original-suite serial sums | 11.77 / 29.15 / 0.72 s | 11.36 / 28.77 / 0.52 s |
| Collection, original-suite serial | 0.90 s | 0.89 s |
| Actual GitHub Actions wall time | Not measured | Not measured; no remote run triggered |

The full parallel run is about 28% faster than the local baseline despite adding
20 cases. The serial improvement is small on a low-latency local database; do not
claim a large serial speedup from noise in one run. The demonstrable database
change is 3,420 fewer SELECT round trips, preserving all eleven cleanup assertions.
The original 37–40 minute run was not reproduced and is not used as the measured
before value. SQL network latency on that original server remains unmeasured.

Four workers save only about three further integration seconds on this host while
using twice the worker databases/decoder/password resources. CI therefore defaults
to two. Local default stays serial for compatibility with schema-only test roles;
the documented two-worker full-suite command is available on disposable servers.
Separate CI test jobs execute complementary fast vs integration/E2E sets, so their
test wall time overlaps; this is not a measured total CI wall-clock duration.
Dependency downloads, Git fetches, runner capacity and queue time must be measured
in GitHub after the user's first authorized PR run.

Parallelization found real harness defects rather than hiding failures: unstable
random parameter IDs caused collection mismatches, and newly created PostgreSQL
databases inherited Europe/Berlin instead of the previous test database's UTC.
Stable case IDs and explicit test-only UTC configuration fixed those causes;
no UTC assertion was relaxed. Runtime random identifiers, production Argon2id,
transaction/constraint checks and synchronized concurrency tests remain intact.

Slow subprocess tests are deliberately retained. Remaining opportunities should
be measured on actual CI: dependency cache effectiveness, job startup overhead,
runner CPU/Argon2 contention and remote PostgreSQL latency. No mutable database or
credential cache was introduced. Fixture reuse beyond immutable password hashes
was avoided because sharing sessions/apps would risk authorization/isolation bugs.

Reliability verification: all 932 tests also pass in reversed collection order
with two workers (30.83 s), with no skipped or xfailed cases. Standalone fast,
integration (serial/two/four workers), E2E and CI-policy module runs pass. Cleanup
verification found zero remaining worker databases or integration schemas.
Ruff, formatting, mypy, actionlint, sanitized real JUnit generation, uv build,
clean wheel import/CLI verification and Alembic upgrade/check/downgrade/re-upgrade
checks were executed successfully. PostgreSQL version 17 and actual GitHub runner
wall time remain to be verified by the first authorized CI run; local measurements
used PostgreSQL 16.14. No external R2 test or release was triggered.
