# Instrumentkategorien

Das vorhandene Feld `type` ist die einzige Instrumentkategorie. Gültige Werte
sind `violin`, `viola`, `cello`, `double_bass` und `bow`. Ein zweites, redundant
gepflegtes Feld `category` gibt es nicht. `ownership` beschreibt weiterhin das
Eigentum und ist unabhängig vom Instrumenttyp.

## Anlage und optionale Angaben

Zur Anlage über `POST /api/v1/instruments` genügt weiterhin `type`. Vorhandene
Anfragen und Datensätze bleiben gültig. Bögen können mit allen vorhandenen
Eigentumskategorien und einer passenden Kundenzuordnung registriert werden.

```json
{"type": "bow", "ownership": "workshop", "bow_weight_g": 60.5}
```

```json
{"type": "violin", "body_length_mm": 355}
```

| Optionales Feld | Einheit | Zulässige Kategorien |
| --- | --- | --- |
| `body_length_mm` | Korpuslänge in Millimetern | `violin`, `viola`, `cello`, `double_bass` |
| `bow_weight_g` | Bogengewicht in Gramm | `bow` |

Beide Angaben sind optional und müssen, wenn gesetzt, endliche positive Zahlen
sein. Nullwerte sind zulässig; Boolean-Werte, Zahlentext, die Zahl 0, negative Zahlen,
NaN und Unendlich sind als Messwerte ungültig. Dabei bedeutet JSON `null`
„nicht erfasst“, die Zahl `0` dagegen einen ungültigen Messwert. Gemeinsame
Angaben wie Hersteller, Baujahr, Kennzeichnung und Notizen bleiben optional.
Weitere kategorienspezifische Angaben können als optionale typisierte Felder
mit passenden API-Regeln und Datenbankmigrationen ergänzt werden; bestehende
Datensätze benötigen dafür keine erfundenen Pflichtangaben.

Alle Instrumentantworten einschließlich Kundenübersichten enthalten die beiden
neuen Felder; nicht erfasste oder unpassende Angaben erscheinen als `null`.
Ungültige Kategorien und widersprüchliche Attribute ergeben HTTP 422.
PostgreSQL-Constraints sichern Kategorie, positive endliche Messwerte und deren
Anwendbarkeit zusätzlich gegen direkte SQL-Schreibzugriffe ab.

## Teiländerungen

`PATCH /api/v1/instruments/{id}` prüft den zusammengeführten Zustand unter der
vorhandenen Zeilensperre. Omission erhält Werte, explizites `null` entfernt einen
Messwert. Die Kategorie selbst darf nicht `null` sein. Unpassende Messwerte
werden bei einem Typwechsel nicht still gelöscht.

Beispiel: Der Wechsel eines Datensatzes mit erfasster Korpuslänge zu einem Bogen
verlangt `{"type": "bow", "body_length_mm": null, "bow_weight_g": 60.5}`.
Nur `{"type": "bow"}` wird in diesem Fall abgewiesen. Umgekehrt muss ein
bestehendes Bogengewicht beim Wechsel zu einer Streichinstrumentkategorie
explizit geleert werden. Kategorie-/Attributänderungen werden weiterhin durch
`instrument.updated` auditiert; die separate Eigentümerhistorie verändert sich
nur, wenn sich auch Eigentum oder Kundenreferenz tatsächlich ändern.

## Filtern

`GET /api/v1/instruments?type=bow` liefert nur Bögen.
`GET /api/v1/instruments?type=bow&ownership=workshop` kombiniert beide Filter mit
UND. Ohne Typfilter bleibt die bisherige Gesamtliste erhalten, ohne Treffer
folgt `[]`. Unbekannte Filterwerte ergeben HTTP 422. Zugriffsschutz und bestehende
Routen bleiben erhalten; der neue Typfilter nutzt einen Datenbankindex.

## Migration

`uv run alembic upgrade head` installiert Revision `c64f95a37d12`. Sie erweitert
den bestehenden Typ-Constraint, fügt zwei nullable Messwertspalten und ihre
Constraints sowie den Typindex hinzu. Bestehende IDs, Kategorien, Details,
Kundenreferenzen und Eigentümerhistorien werden nicht verändert.

Ein Downgrade wird abgebrochen, sobald Bögen oder erfasste neue Messwerte
existieren. Der Betreiber muss vorher deren fachlichen Erhalt klären; die
Migration löscht oder kürzt diese Daten nicht automatisch.
