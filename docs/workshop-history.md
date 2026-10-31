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
Reparatureintrag mit seiner ID. Aktuell ist dies eine Grundlage für dokumentierte
Reparaturarbeiten; ein Auftragsstatus-/Freigabe-, Preis- oder Rechnungsworkflow
wird damit nicht behauptet.

`GET /api/v1/repair-orders/{order_id}` liefert Beschreibung, Daten und die
zugehörigen Dokumentmetadaten eines einzelnen Eintrags. Die gemeinsame
Instrumenthistorie sortiert nach `performed_at` aufsteigend und dann nach ID,
also älteste Arbeiten zuerst. Ein unbekanntes Instrument ergibt HTTP 404;
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
