# Instrumenteigentum und Historie

## Kategorien und aktuelle Zuordnung

| `ownership` | Bedeutung | `customer_id` |
| --- | --- | --- |
| `customer` | Kundeneigentum | Vorhandene positive Kunden-ID oder `null`, wenn der Eigentümer nicht mehr bekannt/verknüpft ist |
| `workshop` | Werkstatteigentum | Muss `null` sein |
| `unassigned` | Noch nicht geklärt/zugeordnet | Muss `null` sein |

`customer_id` bleibt der Eigentümerverweis für die vorhandene Kundenübersicht
und Kundeninstrumentliste. Archivierung verändert diese Zuordnung nicht.
Die Kategorie ist in allen Instrumentantworten enthalten. Werkstattbestand lässt
sich mit `GET /api/v1/instruments?ownership=workshop` auswählen. Die Liste bleibt
ansonsten unverändert. Unbekannte Kategorien und widersprüchliche Kombinationen
liefern HTTP 422; nicht vorhandene Kunden oder Instrumente HTTP 404.

Anlagebeispiele für `POST /api/v1/instruments`:

```json
{"type": "violin", "ownership": "workshop"}
```

```json
{"type": "cello", "ownership": "customer", "customer_id": 7}
```

Bestehende Clients dürfen weiterhin nur `customer_id` angeben: Ohne explizite
Kategorie ergibt eine Kunden-ID `customer`, ohne Kunden-ID `unassigned`.
Fehlende Kundenzuordnung wird niemals automatisch als Werkstatteigentum gedeutet.

## Änderungen

`PATCH /api/v1/instruments/{id}` validiert den zusammengeführten Zustand unter
Zeilensperre. Ein Wechsel von Kunde 7 zu Kunde 8 bleibt mit
`{"customer_id": 8}` möglich. `{"customer_id": null}` ohne Kategorie hebt eine
Kundenzuordnung auf und setzt `unassigned`; vorhandenes Werkstatteigentum bleibt
bei einer solchen leeren Zuordnung erhalten.

Bei explizitem Wechsel zu Werkstattbestand muss eine bisherige Kunden-ID bewusst
geleert werden: `{"ownership": "workshop", "customer_id": null}`. Nur
`{"ownership": "workshop"}` bei einem vorhandenen Kundenverweis liefert HTTP 422
und verändert nichts. `{"ownership": "customer", "customer_id": null}` kann
bewusst Kundeneigentum mit unbekanntem Eigentümer darstellen.

Beim endgültigen Löschen eines Kunden löscht `ON DELETE SET NULL` nur die aktuelle
Kundenreferenz. Die Kategorie bleibt `customer`; das Instrument wird dadurch
nicht Eigentum der Werkstatt. Die Historie bewahrt die frühere Kunden-ID.

## Historie

`GET /api/v1/instruments/{id}/ownership-history` liefert die neuesten Einträge
zuerst. `offset` beginnt bei 0, `limit` ist standardmäßig 100 (erlaubt 1–200).
Ein Eintrag enthält alte/neue Kategorie, alte/neue Kunden-ID, Instrument-ID,
Akteur-ID soweit bekannt, UTC-Zeitpunkt und Quelle (`migration`, `created`,
`changed`). Es werden keine Namen, Kontakte, Notizen oder Zugangsdaten kopiert.

Ein PostgreSQL-Trigger schreibt Anlage und tatsächliche Zuordnungsänderungen in
`instrument_ownership_event` innerhalb derselben Transaktion. Er erfasst auch die
automatische Entkopplung beim Löschen eines Kunden. Unveränderte Zuordnungen und
reine Detailänderungen erzeugen keinen zusätzlichen Eintrag. API-Änderungen
setzen die authentifizierte Akteur-ID transaktionslokal; bei direkten SQL-
Operationen ohne diese Angabe bleibt sie unbekannt. Fehler beim Schreiben der
Historie verhindern den Commit von Instrumentänderung und Audit-Ereignis.

Die vorhandenen Audit-Ereignisse für Anlage, Änderung und Löschung bleiben
bestehen. Diese fachliche Historie ist eigenständig und wird nicht durch die
180-Tage-Standardaufbewahrung des Audit-Protokolls entfernt. Sie bleibt auch nach
Löschen eines Instruments oder Kunden erhalten: IDs sind historische Referenzen
ohne kaskadierende Fremdschlüssel. Instrument- und Kunden-IDs dürfen daher nicht
durch Zurücksetzen der Sequenzen wiederverwendet werden. Der Historienendpunkt
bleibt für ein gelöschtes Instrument mit vorhandener Historie nutzbar; ohne Instrument und ohne Historie
folgt HTTP 404. Es gibt keine schreibende Historien-API.

Nur Administratoren und Mitarbeiter erhalten Zugriff. Historische IDs bleiben
personenbeziehbar; Aufbewahrung und gegebenenfalls Bereinigung müssen vom
Betreiber für diese fachlichen Daten gesondert geregelt werden. Es gibt noch
keine automatische Bereinigung dieser Tabelle. Datenbankrollen benötigen
INSERT-/Sequenzrechte für den Trigger und SELECT für den lesenden Zugriff;
UPDATE/DELETE sollten auf vertrauenswürdige Betreiber begrenzt sein. Ein
privilegierter SQL-Nutzer kann Historie und Akteurzuordnung manipulieren; dies
ist keine manipulationssichere Archivierung.

## Migration und Kompatibilität

`uv run alembic upgrade head` spielt Revision `b53e84f26c01` ein. Vorhandene
Instrumente behalten IDs, Details und Kundenreferenzen. Mit Kundenreferenz wird
`customer`, ohne Referenz `unassigned` eingetragen. Pro Instrument entsteht ein
`migration`-Snapshot am Migrationszeitpunkt. Frühere, bisher nicht gespeicherte
Wechsel oder Erwerbsdaten werden nicht nachträglich erfunden. Neue Felder in
Antworten sind eine additive API-Erweiterung; strikte Clients müssen sie erlauben.

Ein Downgrade entfernt Kategorie und Historie endgültig, erhält aber die dann
aktuellen Instrument- und Kundenreferenzen. Vor einem solchen Schritt müssen
Historie und Kategorien gesichert und der Verlust ausdrücklich akzeptiert sein.
Auch direkte SQL-Schreibzugriffe müssen die neue Kategorie und ihre Constraints
berücksichtigen; automatische Historie setzt die Alembic-Triggerinstallation
voraus, `SQLModel.metadata.create_all()` ist dafür kein Ersatz.
