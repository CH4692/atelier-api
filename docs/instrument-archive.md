# Instrument archival and historical access

Use `PATCH /api/v1/instruments/{instrument_id}/archive` with
`{"is_archived":true}` to archive an instrument, or `{"is_archived":false}` to
restore it. Existing administrator/employee session authorization, HTTPS and CSRF
checks apply. Customers and anonymous requests cannot archive or restore.

The response is the instrument representation, now with `is_archived`. Only an
explicit JSON boolean is accepted; invalid input returns 422 and unknown IDs 404.
Repeated requests for the same state are idempotent and create no duplicate audit
event. Creation and ordinary PATCH do not accept archive state; use the dedicated
endpoint. Existing and newly created instruments default to active in Python and
PostgreSQL, including older direct SQL inserts that omit the new column.

Default instrument listings exclude archived records before filtering, counting,
sorting and pagination. `include_archived=true` includes both active and archived
instruments. This applies to:

- `GET /api/v1/instruments`, including search and X-Total-Count.
- `GET /api/v1/customers/{customer_id}/instruments`.
- The instrument list in `GET /api/v1/customers/{customer_id}/overview`.

Archival is a visibility/lifecycle change, not a physical deletion or an ownership
change. Direct ID retrieval, chronological repair history, documents, ownership
history, photo metadata/content and existing QR links remain accessible to staff.
The integer ID, immutable public UUID, customer association and all historical
foreign keys remain unchanged. Archive does not trigger photo deletion, alter a
photo retention hold, detach a customer or cascade to dependent records. Existing
business operations by ID continue to work; no new rule forbidding edits or work
on an archived instrument is introduced.

`instrument.archived` and `instrument.restored` audit events share the transaction
with the state change and retain the acting user, resource ID and UTC timestamp.
Row locking serializes concurrent archive/restore requests and prevents duplicate
archive events for concurrent identical requests.

## Permanent deletion and referential integrity

`DELETE /api/v1/instruments/{instrument_id}` remains a separate explicit operation.
A repair order or photo referencing the instrument prevents deletion through its
existing `ON DELETE RESTRICT` foreign key. This remains true for archived repair
orders and soft-deleted/pending/held photo metadata. The API rolls back the attempt
and returns 409; no successful deletion audit is retained. Database-level deletion
is blocked as well, and no dependent record is automatically removed.

An instrument without protected dependent records can still be explicitly deleted
through the existing DELETE API. Archival itself never invokes that operation.
Ownership/audit events intentionally retain historical identifiers independently
of resource lifetime, according to the existing design; they are not cascading
child records. Archival retains the full instrument row as the preferred choice
when business records must remain available. No new legal retention duration or
automatic deletion policy is introduced.

## Migration and verification

Run `uv run alembic upgrade head` before deploying. Revision `1b9e40f82c67`, after
`0a8d39e71b56`, adds non-null `is_archived` with a false database default and an
index on `(is_archived,id)`. Existing instruments are active after migration.
No relationship, object key, identifier or historical row is rewritten.
Downgrade refuses to remove archive state while archived instruments exist, so a
rollback cannot silently reactivate them. Review and restore those records before
an intentional downgrade.

Tests cover visibility in all three listing paths, filters/counts/pagination,
restoration, strict input, role and CSRF protection, real restrictive foreign keys,
repair/document/photo/QR preservation, atomic audit rollback, concurrent archival,
and migration backfill/defaults/guarded downgrade. Use the dedicated PostgreSQL
suite: `make test-integration`; use `make test` for complete verification.

## Future rental contracts

Rental-contract models/APIs are not implemented in this repository and are not
added by this change. No rental migration or placeholder table is introduced.

When that feature is implemented, its instrument foreign key must use restrictive
referential integrity without destructive cascades. Active contracts need explicit
business-rule validation before permanent deletion; existing/historical contracts
must keep their instrument references, including archived instruments. Integrate
violations with the existing HTTP 409 behavior and add real PostgreSQL integration
tests for active, historical and archived contract cases. Default active-only
instrument listings must not be used to decide whether an instrument referenced
by a historical contract exists. Archival must never terminate or delete contracts
implicitly.
