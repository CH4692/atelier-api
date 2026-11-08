# Repair change history

`GET /api/v1/repairs/{repair_id}/history` returns retained audit events associated
with a repair, ordered by occurrence timestamp and then event ID, oldest first.
The endpoint requires an active administrator session, matching existing audit
access policy. Employee and customer accounts cannot read it. Authorization runs
before repair lookup; an administrator requesting an unknown repair receives 404.

Each entry includes a unique ID, action, affected resource type/ID, `actor_id`,
UTC `occurred_at`, operation outcome and controlled metadata. Actor references
survive account deactivation/deletion. Older records with no known actor retain
null; the API never infers an actor from current ownership or fabricates past work.

The view includes these existing business events:

- Repair creation and detail changes.
- Repair status changes, including previous and new status.
- Repair archival and restoration.
- Service/material position creation and changes.
- Repair document creation.
- Cost-estimate creation, changes, state transitions and customer approval.

Direct repair events and related resource IDs scope the query. Older child events
without parent metadata are found through their existing relationships. Stored
`repair_order_id` metadata also keeps newer child events associated if a child
is later removed through an authorized retention procedure. Unrelated repairs,
customer changes, authentication and administrative security events are excluded.
The endpoint does not expose raw request bodies, filenames, document contents,
description text, internal note text, passwords or tokens.

## Changes and important timestamps

New repair updates record the exact changed field names in `details.changed_fields`.
Expected-completion-date changes also record `previous_expected_completion_date`
and `new_expected_completion_date`, including null when the date is cleared.
Service/material edits record their changed field names. These field names are
validated against an explicit allowlist. The actual text contents of descriptions
and notes, and previous monetary values, are not copied into audit metadata.
This is a change/event history, not a recoverable version of every text draft.

`occurred_at` records when the operation was recorded. Repair `accepted_at`,
`performed_at`, `created_at` and `status_updated_at` remain available through the
repair detail API; they have different meanings and are not substituted for one
another. Customer approval timestamps remain on the related estimate document.
Old update events that did not record field/date metadata remain readable with
unknown details rather than receiving invented backfills.

History events are the existing persistent PostgreSQL audit records. Creation,
updates, status changes, archival, positions, documents and estimate changes
already append audit facts inside their business transaction. If audit writing
fails, the business change and its history are rolled back together. Rejected
input, invalid transitions and no-op updates do not create successful change
entries. Reading history records `audit.read` outside this repair-event view;
it does not add another repair change or affect the returned count.

## Pagination and protection

Use `offset` (default 0, minimum 0) and `limit` (default 100, allowed 1–200).
`X-Total-Count` reports the matching retained count before pagination, including
on empty pages. Count and page are separate queries and may observe concurrent
commits differently. Invalid pagination or nonpositive repair IDs return 422.
Responses set `Cache-Control: private, no-store` and `Pragma: no-cache`.

Archived repairs remain readable, including when their instrument/customer is
archived. There are no POST/PATCH/DELETE history endpoints. The controlled audit
writer remains the only application write path. Direct privileged SQL remains
an operator capability; this feature does not claim tamper-proof storage.

## Retention and deployment

The view follows the existing `AUDIT_RETENTION_DAYS` policy (default 180 days)
and operator-triggered audit cleanup. It is **not** a second, permanent archive.
Once an event expires and is purged, it is absent from this history. The repair,
its documents, estimate approvals and other business records are not deleted by
audit cleanup. A known repair with no retained events returns an empty list and
count zero. Configure audit retention and backups according to operational needs;
the feature neither extends retention silently nor reconstructs purged events.

No new table or migration is needed: the existing JSON audit metadata accepts the
additional validated field names and ISO date strings. Existing events remain
compatible. The dedicated administrator-only `/api/v1/audit-events` API and its
security policy are retained.

Tests cover attribution, UTC timestamps, status/date changes, related-resource
scoping, chronological ties, pagination boundaries, no-op/invalid operations,
atomic rollback, deactivated/unknown users, archive access, retention, legacy child
metadata, unauthorized access and absence of modification endpoints.
