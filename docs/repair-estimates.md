# Repair cost estimates

Estimates are separate, numbered document revisions attached to a repair. Their
service/material positions are stored in `estimate_item`, not `repair_item`.
Editing actual costs never changes an estimate; approving an estimate neither
copies lines into actual costs nor limits later actual prices. For example, a
15.00 estimate can remain approved while recorded actual costs total 32.50.

## Workflow and traceability

| Current state | Permitted operation | Result |
| --- | --- | --- |
| `draft` | Replace estimated positions | Same draft revision |
| `draft` | Issue / withdraw | `issued` / `withdrawn` |
| `issued` | Record customer approval | `approved` |
| `issued` | Reject / withdraw | `rejected` / `withdrawn` |
| `approved`, `rejected`, `withdrawn` | Read | Stored document retained |

Only drafts can be edited. Once issued, lines, quantities, prices and the
contracting customer cannot be overwritten through application APIs. For a
changed proposal, create a new revision; the previous document remains readable
by its original ID, including its original approval. Revisions are numbered per
repair starting at 1. Creating another revision does not silently revoke or
supersede an earlier approval. Callers must identify the relevant revision; the
application does not choose a single binding/current offer automatically.

The existing contracting customer is copied from the repair, never inferred from
the instrument's current owner. A repair without known customer attribution
cannot receive an estimate. Completed/cancelled repairs reject estimate mutations
with HTTP 409; their recorded estimates remain readable. Archiving does not
remove documents or approval facts. Quote approval and repair workshop status
are separate; recording approval does not automatically change repair status.

## Endpoints

All paths use `/api/v1/repairs/{repair_id}/estimates`:

- `POST` creates a draft with an array of 1–200 positions and returns HTTP 201.
- `GET` lists document summaries ordered by revision. `offset` defaults to 0;
  `limit` defaults to 100 and accepts 1–200. `X-Total-Count` gives the count before
  pagination. Summaries include approval facts; they exclude position contents.
- `GET /{estimate_id}` returns the document, all positions and service, material
  and overall totals, including for approved/historical documents.
- `PATCH /{estimate_id}` replaces the draft's complete `items` array. This is
  array replacement, not a merge by item ID. Draft item IDs can change; issued
  item IDs and values remain stable. No partial header/actor update is accepted.
- `PATCH /{estimate_id}/status` accepts `{"status":"issued"}`, `rejected` or
  `withdrawn` through the state machine. Repeating the current permitted target
  returns the same document without another event or timestamp. Other transitions
  return HTTP 409; use the dedicated approval operation for `approved`.
- `POST /{estimate_id}/approval` records one customer's approval of the issued
  snapshot. Repeating an approval returns HTTP 409; it cannot replace the first
  recorded approval metadata.

Example draft:

```json
{
  "items": [
    {"kind":"service", "description":"Bridge fitting", "quantity":"1.500", "unit_price":"40.00"},
    {"kind":"material", "description":"Bridge blank", "quantity":"1", "unit_price":"25.50"}
  ]
}
```

Positions reuse the actual-cost validation and arithmetic policy: description
1–2000 trimmed characters, quantity greater than zero up to 999999.999 with
three fractional places, nonnegative unit price up to 9999999999.99 with two
fractional places. Decimal values are returned as JSON strings. Each line is
rounded HALF_UP to cents before adding line amounts. No float arithmetic,
independent editable total, tax calculation or currency conversion is introduced.
Use the same workshop currency convention as actual costs.

## Recording customer approval

```json
{
  "approved_at": "2026-11-01T15:30:00+01:00",
  "approval_method": "email",
  "approval_reference": "Correspondence reference"
}
```

`approved_at` must include a timezone and lie between the document's stored issue
time and the server's recording time. It is returned in UTC. Supported methods
are `in_person`, `phone`, `email`, and `written`. The optional reference is trimmed,
blank becomes null, and its length is limited to 500 characters. Store only a
necessary correspondence reference rather than copying personal correspondence.

The document records both the actual approval timestamp and the server recording
timestamp, the original customer's ID and the authenticated staff recorder's ID.
Actor IDs are application-controlled and retained independently of account
lifetime. No client-supplied recorder/customer/status/timestamp overrides are
accepted. This endpoint is a staff record of approval received outside the app;
it does not authenticate a customer, send email, capture a signature or generate
a PDF. Customer portal accounts cannot access these internal documents.

## Authorization, transactions and migration

Every endpoint requires a current administrator/employee session. Mutations use
the existing Origin/CSRF checks. Responses use `private, no-store`. Unknown repairs,
unknown estimates and cross-repair estimate IDs return HTTP 404. Invalid input
returns HTTP 422; invalid document/repair state returns HTTP 409.

Writers lock the parent repair and then the estimate. This serializes revision
allocation, issue/approval versus draft edits, and quote changes versus repair
completion. Detail readers take a shared document lock, so header, lines and
totals cannot describe different draft versions. Listing count and page are
separate statements and can observe concurrent commits differently.

Every creation, edit, state change and approval records an explicit audit event
in the business transaction. Events contain acting-user and estimate/repair IDs
and status facts, not position descriptions, prices or approval references. Audit
failure rolls back document changes too, including draft position replacement.
Approvals and their positions remain stored even after audit-event retention
removes older audit rows.

Apply migration `b83e71f09526` with `uv run alembic upgrade head`. It creates the
two new tables and preserves existing repairs and actual costs. Restrictive
foreign keys preserve repair/customer associations and prevent cascading deletion.
The migration refuses a downgrade when estimates or estimated positions exist;
plan export/review before rollback. There is no permanent estimate-deletion API.
As with other records, privileged direct SQL can bypass application immutability;
this is not tamper-proof storage or an immutable legal-signature archive.
