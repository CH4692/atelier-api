# Repair status tracking

This feature extends the existing repair intake, editing, listing and document
APIs with a validated status workflow.
All paths use the existing `/api/v1` prefix and require an authenticated employee
or administrator. Customer accounts cannot read repair notes or change status.
Mutations also require the existing Origin/CSRF protection.

## API

- `POST /api/v1/repairs`: supply existing `customer_id`, `instrument_id` and a
  nonblank `work_description` (trimmed, 1–10000 characters). Optional fields are
  `expected_completion_date` and `internal_notes` (at most 10000 characters).
  Returns HTTP 201. Unknown references return HTTP 404. The existing intake
  contract defaults to `accepted` and permits explicit initial status and intake
  dates for data entry. Subsequent status changes use the validated endpoint.
  Client-supplied `status_updated_at` is rejected.
- `GET /api/v1/repairs/{repair_id}`: returns the order and current `status` and
  `status_updated_at`, or HTTP 404. All successful repair responses include the
  current status and timezone-aware UTC timestamps and use `private, no-store`.
- `PATCH /api/v1/repairs/{repair_id}/status`: accepts `{"status": "in_progress"}`
  and returns HTTP 200 with the updated order. Unknown status values, missing
  status and unexpected fields return HTTP 422. A valid status that is not a
  permitted transition returns HTTP 409. Unknown orders return HTTP 404.

## State machine

| Current status | Allowed next statuses |
| --- | --- |
| `accepted` | `awaiting_approval`, `in_progress`, `cancelled` |
| `awaiting_approval` | `in_progress`, `cancelled` |
| `in_progress` | `awaiting_approval`, `awaiting_materials`, `ready_for_pickup`, `cancelled` |
| `awaiting_materials` | `in_progress`, `cancelled` |
| `ready_for_pickup` | `in_progress`, `completed`, `cancelled` |
| `completed` | None |
| `cancelled` | None |

An order can return from ready-for-pickup to work if further work is needed.
Completion requires ready-for-pickup. Completed and cancelled orders cannot be
reopened. Reassigning the current state is an idempotent no-op, including for
terminal states: no new timestamp or audit event is written. This supports safe
retries after a client loses the response.

For newly registered managed orders, `status_updated_at` initially equals
`accepted_at`. Existing orders and historical work entries retain null because
their previous status-change times are unknown. Actual changes receive a
server-generated UTC timestamp. A backwards wall-clock adjustment cannot move
this timestamp backwards. Clients cannot overwrite it. Each actual change emits
`repair_order.status_changed` with actor/resource IDs and previous/new statuses;
notes and descriptions are excluded. The audit event has its own UTC occurrence
time and follows the existing audit retention policy. `status_updated_at` is the
latest-change timestamp, not a complete permanent status-history table.

Status validation runs after acquiring a PostgreSQL row lock and refreshing the
order. Concurrent requests therefore validate against the latest committed
state. State, timestamp and audit event commit atomically; an audit failure
rolls back the change. The state machine is enforced by controlled application
operations. Database checks enforce status values and timestamp ordering, but
privileged direct SQL can bypass transition rules; this is not tamper-proof
storage.

## Migration and operation

Apply migration `f36b9a208d71` with `uv run alembic upgrade head` using the intended
deployment database. This migration extends the existing `repair_order` table
after `2caf51093d78`; it does not recreate repairs or documents. Existing customers,
instruments, repairs and documents remain unchanged apart from the nullable new
column; no historical status dates or customer attribution are invented. Repair references use
`ON DELETE RESTRICT`; attempts to delete referenced customers or instruments
return HTTP 409. No cascading deletion of repairs is introduced.

The downgrade refuses to remove non-null status timestamps. Review/export records
and plan any rollback before removing this migration. Test migration commands
only against dedicated disposable databases, never production. The existing repair document storage, general detail editing, pagination and
archiving APIs remain available.

Tests cover all 49 status pairs, HTTP validation, no-op retries, terminal states,
UTC timestamps, database constraints, authorization/CSRF, audit rollback,
migration safeguards and independent committed concurrent transactions.
