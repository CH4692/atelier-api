# Werkstatthistorie eines Instruments

`GET /api/v1/instruments/{id}/history` ist die gemeinsame Detailansicht für das
Instrument und seine Reparatureinträge. Sie liefert `instrument` mit den
vorhandenen Instrumentfeldern und `repair_orders` mit Arbeitsbeschreibungen,
Reparaturzeitpunkten, Archivstatus und Dokumentmetadaten. Die bisherigen
Instrument-GET-Endpunkte und Listen behalten ihr Antwortformat.

## Reparaturen erfassen und lesen

```text
POST /api/v1/instruments/{id}/repair-orders
```

```json
{
  "work_description": "Steg ersetzt und Stimmstock angepasst",
  "performed_at": "2026-01-15T14:00:00+01:00"
}
```

Eine Arbeitsbeschreibung mit 1–10000 Zeichen nach dem Trimmen und ein expliziter
Reparaturzeitpunkt mit Zeitzone sind erforderlich. Zeitpunkte werden als UTC
zurückgegeben. `created_at` bezeichnet die Erfassung, nicht das Reparaturdatum.
So können auch frühere Arbeiten nachgetragen werden, ohne historische Daten aus
der Reihenfolge ihrer Eingabe abzuleiten. Ungültige Angaben ergeben HTTP 422,
ein unbekanntes Instrument HTTP 404. Die Anlage liefert HTTP 201 und den
Reparatureintrag mit seiner ID und dem Status `completed`. Dieser bestehende
Erfassungsweg bleibt für historische Arbeiten erhalten. Kundenreferenz und
Annahmezeitpunkt bleiben dabei unbekannt; sie werden nicht aus dem heutigen
Instrumenteigentümer oder dem Erfassungsdatum abgeleitet.

`GET /api/v1/repair-orders/{order_id}` liefert Beschreibung, Daten und die
zugehörigen Dokumentmetadaten eines einzelnen Eintrags. Die gemeinsame
Instrumenthistorie sortiert nach `performed_at` aufsteigend und dann nach ID,
also älteste Arbeiten zuerst. Aufträge ohne Ausführungszeitpunkt stehen danach. Ein unbekanntes Instrument ergibt HTTP 404;
ein bekanntes Instrument ohne Reparaturen erhält `repair_orders: []`.

Die Reparaturliste wird mit `offset` (Standard 0) und `limit` (Standard 100,
zulässig 1–200) paginiert. `X-Total-Count` enthält die Gesamtzahl einschließlich
archivierter Einträge. Für die vollständige Historie sind gegebenenfalls weitere
Seiten abzurufen. Auf einer leeren Seite bleiben Instrumentdetails und Gesamtzahl
verfügbar. Count und Seite sind getrennte Abfragen und können gleichzeitige
Commits unterschiedlich beobachten. Dokumentmetadaten für eine Seite werden in
einer gemeinsamen Abfrage geladen; Dokumentinhalte werden dabei nicht gelesen.

## Dokumente

Upload als unveränderte Binärdaten, nicht als Multipart-Formular:

```text
POST /api/v1/repair-orders/{order_id}/documents?filename=reparatur.pdf
Content-Type: application/octet-stream
```

Beispiel mit bestehender Session:

```bash
curl --fail-with-body -b /private/tmp/atelier-cookies.txt \
  -H 'Origin: http://127.0.0.1:8000' -H 'X-CSRF-Protection: 1' \
  -H 'Content-Type: application/octet-stream' --data-binary @reparatur.pdf \
  'http://127.0.0.1:8000/api/v1/repair-orders/7/documents?filename=reparatur.pdf'
```

Pro Dokument sind 1 Byte bis 5 MiB erlaubt; der Request wird beim Lesen begrenzt.
Zu große Inhalte ergeben HTTP 413, leere Inhalte oder ungültige Dateinamen HTTP
422, andere Content-Types HTTP 415. Dateinamen dürfen maximal 255 Zeichen haben;
Pfadbestandteile werden entfernt, Steuerzeichen zurückgewiesen. Dokumente werden
in PostgreSQL gespeichert und sind damit nicht vom flüchtigen Render-Dateisystem
abhängig. Externe URLs werden nicht abgerufen, Upload-Inhalte nicht ausgeführt.

Die Antwort HTTP 201 enthält nur ID, Reparatur-ID, Dateiname, Größe, SHA-256 und
Erfassungszeitpunkt. Dieselben Metadaten stehen an der jeweiligen Reparatur in
der Historie; fremde Dokumente werden nicht eingemischt. Der separate Download
lautet `GET /api/v1/repair-documents/{document_id}/content`. Er verlangt dieselbe
Workshop-Berechtigung, liefert die gespeicherten Bytes als Attachment mit
`application/octet-stream`, `nosniff` und `private, no-store`. Es gibt weder eine
öffentliche Datei-URL noch eine HTML-Vorschau. Der SHA-256 erlaubt eine Prüfung
der heruntergeladenen Bytes, ist aber keine kryptographische Archivversiegelung.

## Archivierung und Erhalt

`PATCH /api/v1/repair-orders/{order_id}/archive` mit `{"is_archived": true}`
archiviert, mit `false` stellt wieder her. Wiederholte Zuweisung desselben Wertes
ist ein No-op. Reparaturen und ihre Dokumente bleiben in der Instrumenthistorie
und direkt abrufbar, auch wenn die Reparatur oder der Kunde archiviert wurde.
Ein Wechsel des aktuellen Instrumenteigentümers verändert diese instrumentbezogene
Historie ebenfalls nicht.

Reparaturen verweisen mit `ON DELETE RESTRICT` auf das Instrument, Dokumente
ebenfalls auf ihre Reparatur. Ein Instrument mit Reparaturhistorie kann deshalb
nicht über die normale Lösch-API entfernt werden (HTTP 409). Es gibt keine
Lösch-API für Reparatureinträge oder Dokumente. Archivierung löscht keine Daten;
fachliche Aufbewahrung und gegebenenfalls kontrollierte Bereinigung bleiben
Betreiberaufgaben. Backups enthalten jetzt auch die Dokumentbytes. Die separate
Audit-Aufbewahrung entfernt keine fachlichen Reparatur- oder Dokumentdaten.

## Zugriff, Migration und Grenzen

Alle neuen Endpunkte verlangen eine aktuelle Session als Administrator oder
Mitarbeiter. Kundenkonten, anonyme Zugriffe und unzulässige CSRF-Anfragen erhalten
keinen Zugriff. Anlage und Archivierung erzeugen explizite Audit-Ereignisse mit
Akteur-/Ressourcen-IDs; Beschreibungen, Dateinamen und Dokumentinhalte werden nicht
in Audit-Daten kopiert. Fachliche Änderung und Audit werden atomar committet.

Revision `d75a06b48e23` wird mit `uv run alembic upgrade head` eingespielt. Bestehende
Instrumente, Kundenzuordnungen und Eigentümerhistorien werden nicht verändert.
Eine leere Reparaturhistorie behauptet keine unbekannten früheren Arbeiten;
solche Daten müssen mit bekannten Zeitpunkten nachgetragen werden. Ein Downgrade
bricht ab, sobald Reparaturen oder Dokumente existieren, statt sie still zu löschen.

Es handelt sich um gespeicherte Arbeitsbeschreibungen, keine unveränderliche
Versionierung jedes Textentwurfs. Direkte privilegierte SQL-Zugriffe bleiben in
der Verantwortung des Betreibers. Speicherbedarf, Backup-Aufbewahrung und
betrieblich notwendige Dokumentprüfung müssen beim Betrieb berücksichtigt werden;
dieses Feature richtet keinen externen Dokumenten- oder Backupdienst ein.

## Customer-linked repair intake

`POST /api/v1/repairs` accepts new managed orders. All business API paths use
the `/api/v1` prefix; `/repairs` is relative to that prefix. The existing
`POST /api/v1/repair-orders` remains available with the same behavior and schema:

```json
{
  "customer_id": 12,
  "instrument_id": 34,
  "work_description": "Replace bridge",
  "expected_completion_date": "2026-12-15",
  "internal_notes": "Confirm setup with customer"
}
```

Both references must exist (otherwise HTTP 404). The contracting customer need
not be the current instrument owner. The response is HTTP 201 with a unique ID.
`accepted_at` defaults to the current UTC time; an explicitly supplied timestamp
must include a timezone. `performed_at` is optional and stays null until known.
`expected_completion_date` and `internal_notes` are optional. Descriptions are
trimmed and limited to 1–10000 characters; notes to 10000 characters. Invalid
input returns HTTP 422. No notes or descriptions are copied into audit events.

`status` defaults to `accepted` and accepts `accepted`, `awaiting_approval`,
`in_progress`, `awaiting_materials`, `ready_for_pickup`, `completed`, and
`cancelled`. Subsequent status changes use
`PATCH /api/v1/repairs/{repair_id}/status` and the state machine documented in
[Repair status tracking](repair-status.md). Details, lists and instrument history
include `status_updated_at`; unknown historical change dates remain null.
Approval, pricing and invoicing workflows are separate features. Internal notes share the existing staff-only
authorization of repair records and are never exposed to customer accounts.

Migration `2caf51093d78` preserves existing repair IDs, execution timestamps and
documents. Historical entries receive `completed` but retain null customer and
acceptance fields because those historical facts are unknown. New managed orders
require both references and an acceptance timestamp. Do not interpret unknown
legacy attribution as the instrument's current owner.

The customer foreign key uses `ON DELETE RESTRICT`, as does the instrument
reference. Customer or instrument deletion with linked orders returns HTTP 409;
archiving and ownership changes preserve the original contracting customer.
There is no cascading deletion. The migration refuses a downgrade if managed
intake data would be lost; review and export that data before any rollback.

## List and retrieve repair orders

`GET /api/v1/repairs` returns an array of repair orders sorted by ascending ID.
Optional `status` and positive `customer_id` query parameters are combined with
AND. Customer filtering uses the recorded contracting customer, not today's
instrument owner; unattributed historical entries do not match a customer filter.
An unknown customer filter or a filter without matches returns an empty array.

Use `offset` (default 0, minimum 0) and `limit` (default 100, range 1–200).
`X-Total-Count` reports the matching count before pagination, including on empty
pages. Invalid status, customer ID or pagination values return HTTP 422. Count
and page queries may observe different concurrent commits. Archived repairs are
excluded by default; `include_archived=true` includes them.

`GET /api/v1/repairs/{repair_id}` returns the order with document metadata,
including archived orders, or HTTP 404 if unknown. The existing
`GET /api/v1/repair-orders/{order_id}` remains available. Both new GET endpoints
require staff authorization and return `Cache-Control: private, no-store`. List
responses exclude document contents and metadata; details include metadata only.

## Update repair orders

`PATCH /api/v1/repairs/{repair_id}` accepts any subset of `work_description`,
`expected_completion_date` and `internal_notes` and returns HTTP 200 with the
updated order. Omitted fields retain their values. A description must contain
1–10000 characters after trimming; null and blank descriptions return HTTP 422.
An ISO date or null sets or clears the expected completion date. Notes accept
up to 10000 characters; null or blank text clears them. Unknown fields and
invalid values return HTTP 422, unknown orders HTTP 404 (also for empty patches).

Customer/instrument references, status, acceptance/execution timestamps and archive
state cannot be changed through this patch. Archived and historical orders remain
editable by authorized staff. Documents and historical customer references are
preserved. An empty patch or unchanged normalized values are a no-op. Actual
changes append `repair_order.updated` with actor/resource IDs in the same
transaction; descriptions and notes are not copied into the audit trail.
Concurrent updates lock the order while applying only supplied fields. The
response uses `Cache-Control: private, no-store`; authentication, staff access
and CSRF protection apply as for order creation.

## Services and materials

Repair services, material positions and exact cost totals are available through
`/api/v1/repairs/{repair_id}/items`. See [Repair services and materials](repair-items.md)
for inputs, partial updates, monetary rounding and completion guards.

## Cost estimates

[Repair cost estimates](repair-estimates.md) provide independent service/material
positions, numbered document revisions and recorded customer approval. Approved
estimates remain readable while actual repair costs can be recorded separately.

## Repair change events

Administrators can retrieve the retained change trail for an individual repair
through `GET /api/v1/repairs/{repair_id}/history`. See
[Repair change history](repair-change-history.md) for attribution, status/date
metadata, pagination, access restrictions and the existing audit-retention limits.
