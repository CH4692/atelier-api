# Repair services and materials

Repair positions belong to exactly one repair order. Each position has an
integer ID, `kind` (`service` or `material`), `description`, `quantity` and
`unit_price`. An order may contain multiple positions of either kind. Existing
repairs start with no positions; no amounts are inferred from descriptions.

## API

All endpoints use the existing staff authorization and CSRF rules:

- `POST /api/v1/repairs/{repair_id}/items`: add a position (HTTP 201).
- `PATCH /api/v1/repairs/{repair_id}/items/{item_id}`: change any subset of
  `kind`, `description`, `quantity` and `unit_price` (HTTP 200). Omitted values
  remain unchanged; explicit null and unknown fields are rejected. Empty or
  unchanged patches return the item without another update audit event.
- `GET /api/v1/repairs/{repair_id}/items`: return all positions ordered by ID,
  together with `service_total`, `material_total` and `total`. These totals use
  the same fetched position rows, so concurrent changes cannot make the returned
  subtotals disagree with the returned positions. An empty order returns an empty
  array and zero totals. Existing repair detail/list response shapes are retained;
  the positions and totals are available through this dedicated endpoint.

Example request:

```json
{
  "kind": "material",
  "description": "Bridge blank",
  "quantity": "1.000",
  "unit_price": "25.50"
}
```

Responses include the position ID, `repair_order_id` and calculated `line_total`.
Decimal quantities and amounts are JSON strings; clients should send decimal
strings to preserve exact input precision. The description is trimmed and must
contain 1–2000 characters. Quantities must be greater than zero and at most
`999999.999`, with up to three significant fractional digits. Prices must be
nonnegative and at most `9999999999.99`, with up to two significant fractional
digits. Free positions are allowed. NaN, infinity, negative prices, zero/negative
quantities and excess precision return HTTP 422. Trailing zeroes do not change
precision. The API validates precision before PostgreSQL stores numeric values;
privileged direct SQL writes may be rounded by PostgreSQL's numeric column types.

Unknown repairs or items return HTTP 404. An item belonging to another repair
also returns HTTP 404. Completed or cancelled repairs reject all item mutations
with HTTP 409, including empty patches. `ready_for_pickup` remains editable until
completion. Archiving alone is not finalization and does not remove positions or
prevent edits on an otherwise active order. Stored historical work already marked
completed remains read-only for cost positions. Read access to positions and
totals remains available after completion, cancellation or archival.

## Monetary policy

Quantities use PostgreSQL `NUMERIC(9,3)`, unit prices `NUMERIC(12,2)`, and all
arithmetic uses Python `Decimal` in an explicit decimal context. For each line:

```text
line_total = round_half_up(quantity * unit_price, 2 decimal places)
service_total = sum(line_total for service positions)
material_total = sum(line_total for material positions)
total = service_total + material_total
```

For example, three positions each with quantity `0.5` and unit price `0.01`
produce three line totals of `0.01` and an order total of `0.03`. Rounding only
the unrounded aggregate would produce `0.02` and is deliberately not used.

Totals are derived from stored quantities and prices rather than independently
editable columns, preventing stale totals after an edit. All positions in the
application's workshop use the same accounting currency; this feature neither
assigns a currency nor performs conversion, tax calculation or invoicing. Prices
are the workshop's recorded per-unit charge, including for materials. Operators
must use a consistent currency and pricing convention.

## Integrity and deployment

Item changes lock the parent repair with the same PostgreSQL row lock used by
status changes. An edit waiting behind completion rechecks the latest status and
fails instead of modifying finalized costs. Item changes and explicit
`repair_item.created`/`repair_item.updated` audit events commit atomically. Audits
include item, repair and acting-user identifiers; descriptions, prices and
quantities are not copied to audit metadata. Authentication, CSRF checks and
`Cache-Control: private, no-store` protect item responses. Customer accounts have
no access to these internal cost records.

Apply migration `a72d90e46c15` with `uv run alembic upgrade head`. The repair
foreign key uses `ON DELETE RESTRICT` and never cascades deletion into cost
positions. Existing customer/instrument deletion protection is preserved. A
downgrade refuses to drop a populated item table; review and export recorded costs
before planning a rollback. API finalization rules are application controls;
privileged database operators can bypass them with direct SQL.

Tests cover fractional quantities, commercial rounding, separate subtotals,
partial edits, missing and cross-repair references, input/database constraints,
authorization/CSRF, terminal-state guards, audit rollback, migrations and a
concurrent edit blocked by a real completion transaction.
