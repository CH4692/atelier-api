### Pytest results

Tests: 558 · passed: 558 · failed: 0 · errors: 0 · skipped: 0 · duration: 18.11 s

Slowest test cases (including fixture time):

| Seconds | Test |
|---:|---|
| 2.775 | `tests.atelier_api.test_release_build::test_pretag_build_tag_checkout_and_gitless_source_archive_agree` |
| 1.087 | `tests.atelier_api.test_release_build::test_first_release_and_repeated_release_are_safe` |
| 0.855 | `tests.atelier_api.test_release_build::test_semantic_release_tags_original_commit_without_branch_changes[case-b5b37e7636]` |
| 0.832 | `tests.atelier_api.test_release_build::test_semantic_release_tags_original_commit_without_branch_changes[case-df81d65b34]` |
| 0.831 | `tests.atelier_api.test_release_build::test_semantic_release_tags_original_commit_without_branch_changes[case-8d5713d98b]` |
| 0.820 | `tests.atelier_api.test_release_build::test_semantic_release_tags_original_commit_without_branch_changes[case-8d6b8bdb68]` |
| 0.748 | `tests.atelier_api.test_release_build::test_semantic_release_tags_original_commit_without_branch_changes[case-329c68e1a9]` |
| 0.747 | `tests.atelier_api.test_release_build::test_semantic_release_tags_original_commit_without_branch_changes[case-67319dba9e]` |
| 0.721 | `tests.atelier_api.test_release_build::test_semantic_release_tags_original_commit_without_branch_changes[case-4a8116c36f]` |
| 0.701 | `tests.atelier_api.test_release_build::test_semantic_release_tags_original_commit_without_branch_changes[case-8e200f29cd]` |
| 0.691 | `tests.atelier_api.test_release_build::test_semantic_release_tags_original_commit_without_branch_changes[case-994e2d7642]` |
| 0.476 | `tests.atelier_api.test_release_configuration::test_release_build_stops_if_tool_installation_fails` |
| 0.467 | `tests.migrations.test_configuration::test_offline_postgresql_sql_uses_environment_without_connecting` |
| 0.451 | `tests.migrations.test_configuration::test_online_connection_failure_is_actionable_and_hides_credentials` |
| 0.231 | `tests.atelier_api.test_release_guard::test_main_advancing_after_checkout_blocks_release` |
| 0.211 | `tests.atelier_api.test_release_guard::test_commit_message_and_actor_do_not_suppress_tested_changes[case-ece2672c54]` |
| 0.211 | `tests.atelier_api.test_release_guard::test_bot_message_prefix_alone_does_not_suppress_release` |
| 0.207 | `tests.atelier_api.test_release_guard::test_commit_message_and_actor_do_not_suppress_tested_changes[case-8cc2f4486d]` |
| 0.206 | `tests.atelier_api.test_release_guard::test_commit_message_and_actor_do_not_suppress_tested_changes[case-53e4ced417]` |
| 0.190 | `tests.atelier_api.test_main::test_swagger_interceptor_preserves_requests_and_defaults_missing_method_to_get` |
### Pytest results

Tests: 932 · passed: 932 · failed: 0 · errors: 0 · skipped: 0 · duration: 30.89 s

Slowest test cases (including fixture time):

| Seconds | Test |
|---:|---|
| 3.246 | `tests.integration.test_photo_purge::test_retention_migration_preserves_data_and_guards_holds` |
| 2.692 | `tests.atelier_api.test_release_build::test_pretag_build_tag_checkout_and_gitless_source_archive_agree` |
| 1.083 | `tests.atelier_api.test_release_build::test_first_release_and_repeated_release_are_safe` |
| 0.968 | `tests.atelier_api.test_release_build::test_semantic_release_tags_original_commit_without_branch_changes[case-8d6b8bdb68]` |
| 0.949 | `tests.atelier_api.test_release_build::test_semantic_release_tags_original_commit_without_branch_changes[case-b5b37e7636]` |
| 0.940 | `tests.integration.test_instrument_photos::test_photo_upload_and_private_retrieval[case-f9dd08f77d]` |
| 0.898 | `tests.integration.test_auth::test_login_cookie_and_authenticated_account[case-cf293a5990]` |
| 0.875 | `tests.atelier_api.test_release_build::test_semantic_release_tags_original_commit_without_branch_changes[case-329c68e1a9]` |
| 0.832 | `tests.atelier_api.test_release_build::test_semantic_release_tags_original_commit_without_branch_changes[case-8d5713d98b]` |
| 0.813 | `tests.atelier_api.test_release_build::test_semantic_release_tags_original_commit_without_branch_changes[case-df81d65b34]` |
| 0.776 | `tests.atelier_api.test_release_build::test_semantic_release_tags_original_commit_without_branch_changes[case-67319dba9e]` |
| 0.772 | `tests.atelier_api.test_release_build::test_semantic_release_tags_original_commit_without_branch_changes[case-8e200f29cd]` |
| 0.748 | `tests.atelier_api.test_release_build::test_semantic_release_tags_original_commit_without_branch_changes[case-4a8116c36f]` |
| 0.710 | `tests.atelier_api.test_release_build::test_semantic_release_tags_original_commit_without_branch_changes[case-994e2d7642]` |
| 0.494 | `tests.migrations.test_configuration::test_online_connection_failure_is_actionable_and_hides_credentials` |
| 0.467 | `tests.migrations.test_configuration::test_offline_postgresql_sql_uses_environment_without_connecting` |
| 0.338 | `tests.integration.test_users::test_deactivation_revokes_old_identity_and_reactivation_does_not_restore_it` |
| 0.331 | `tests.integration.test_users::test_customer_association_is_explicit_unique_and_does_not_enable_portal` |
| 0.329 | `tests.integration.test_instrument_lifecycle::test_instrument_management_lifecycle` |
| 0.298 | `tests.integration.test_users::test_role_changes_revoke_existing_identity` |
