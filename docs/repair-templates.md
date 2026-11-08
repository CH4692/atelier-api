# Repair templates

Authenticated workshop employees and administrators can manage reusable defaults:

- `POST /api/v1/repair-templates`: create with `name` (1–100 characters),
  `description` (1–2000 characters) and optional `default_unit_price`.
- `GET /api/v1/repair-templates`: list in ascending ID order, with `offset` (>=0),
  `limit` (1–200, default 100) and `X-Total-Count`.
- `PATCH /api/v1/repair-templates/{id}`: update future defaults. Omitted fields
  stay unchanged; `default_unit_price: null` clears the price. Text cannot be null.

Text is trimmed and must not be blank. Prices use the existing decimal unit-price
rules: nonnegative, at most two fractional digits, maximum 9999999999.99. Send
monetary values as JSON strings to preserve precision. Zero is a valid price;
an absent price is not interpreted as free work. Invalid input returns 422,
unknown template IDs return 404. There is no template deletion endpoint.

## Select a template at intake

`POST /api/v1/repairs` (also `/api/v1/repair-orders`) accepts, for example:

```json
{
  "customer_id": 1,
  "instrument_id": 1,
  "template_id": 2,
  "work_description": "Fit a bridge for this instrument",
  "template_unit_price": "55.00"
}
```

With `template_id`, omitted `work_description` is copied from the template.
An explicit nonblank description overrides it. Without a template, a description
is still required, preserving ordinary intake behavior.

If the template has a price, intake creates one ordinary **service** position
with quantity 1, the template's description and the copied default unit price.
`template_unit_price` overrides that price. Explicit null suppresses the position;
when neither the template nor the request provides a price, no position is created.
A price override requires a template. Repair description overrides and service-line
text are separate: use the existing item PATCH endpoint to customize the latter,
quantity or price before finalization. All existing rounding and finalization rules
apply. A template is a convenience default, not a customer-approved estimate.

Template selection copies values, with no live reference used to calculate repair
text or costs. Later template edits affect only future intakes. Repair edits never
update the template. Existing repairs and legacy history need no backfill.
The selected template ID is retained in the repair creation audit metadata.

## Persistence and security

Apply migration `c94e82a10637` with `uv run alembic upgrade head` before deployment.
It adds only `repair_template`; existing repair data is unchanged. Downgrade refuses
to drop a nonempty template table. The table has database checks for text and price
bounds. Alembic registers the model independently of application startup.

Intake locks the selected template while copying it, so concurrent template edits
cannot mix description and price versions. Repair creation, initial item and their
audit events commit in one transaction. Template creation/updates also write audit
events atomically; no-op template PATCH does not create an event. Audit metadata
contains identifiers, not template text. Standard audit retention applies.
The existing session, workshop-role and CSRF enforcement also protects these routes;
customer accounts cannot manage templates. Responses use `private, no-store`.
