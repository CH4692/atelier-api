# Instrumentensuche

`GET /api/v1/instruments` liefert weiterhin eine Liste von `InstrumentRead`.
Alle Such- und Filterparameter werden vor Pagination und Zählung mit UND
kombiniert. Der bestehende Zugriffsschutz für Administratoren und Mitarbeiter
bleibt erhalten; eine Kunden-ID im Filter gibt Kundenkonten keinen Zugriff.

| Parameter | Bedeutung / Standard |
| --- | --- |
| `q` | Teilwortsuche in `identification_number`, ohne Beachtung der Groß-/Kleinschreibung, maximal 200 Zeichen |
| `type` | `violin`, `viola`, `cello`, `double_bass` oder `bow` |
| `customer_id` | Positive ID des aktuell zugeordneten Eigentümers |
| `ownership` | `customer`, `workshop` oder `unassigned` |
| `offset` | Übersprungene Treffer, mindestens 0, Standard 0 |
| `limit` | Seitengröße 1–200, Standard 100 |
| `sort_by` | `id`, `identification_number`, `type`, `maker`, `year_of_manufacture`, `customer_id` oder `ownership`; Standard `id` |
| `sort_order` | `asc` oder `desc`; Standard `asc` |

Beispiel:

```text
/api/v1/instruments?q=VIN-&type=violin&customer_id=7&ownership=customer&limit=25&offset=0&sort_by=identification_number&sort_order=asc
```

`q` wird außen getrimmt. Fehlende oder ausschließlich leere Suchbegriffe begrenzen
die Suche nicht. `%`, `_` und andere SQL-Sonderzeichen werden wörtlich gesucht;
Werte werden als gebundene SQL-Parameter übergeben. Bei einer nichtleeren Suche
passen Instrumente ohne Identifikationsnummer nicht zum Suchbegriff. Ohne Suche
bleiben sie in der Liste. Identifikationsnummern sind weiterhin nicht eindeutig.

Eigentümerfilter beziehen sich auf die aktuelle Kundenreferenz, nicht auf die
separate Eigentümerhistorie. Archivierte Eigentümer behalten ihre Zuordnungen.
Nicht vorhandene Eigentümer-IDs und widerspruchsfreie, aber nicht passende
Filterkombinationen liefern `[]`, keinen Kunden-404-Fehler.

Ergebnisse werden vor SQL LIMIT/OFFSET sortiert. Nullwerte stehen in beiden
Richtungen zuletzt. Bei gleichen Werten entscheidet aufsteigend die eindeutige
Instrument-ID; dadurch haben Seiten bei unveränderten Daten eine stabile Ordnung.
Textsortierung verwendet die Datenbank-Kollation. Ohne Treffer oder hinter der
letzten Seite folgt `[]`.

Der Header `X-Total-Count` enthält die Anzahl aller Treffer vor Pagination, auch
bei einer leeren Seite. Er ist über die vorhandene CORS-Konfiguration für
zugelassene Browser-Clients lesbar. Beispiel: Drei Treffer ergeben bei
`offset=3&limit=2` den Body `[]` und `X-Total-Count: 3`. Count und Seitendaten werden
getrennt abgefragt und können gleichzeitige Commits unterschiedlich beobachten.
Auch über mehrere Requests hinweg ist dies kein eingefrorener Daten-Snapshot.

Ungültige Werte, unbekannte Sortierfelder/-richtungen, nichtpositive Eigentümer-
IDs, negative Offsets und Seitengrößen außerhalb der Grenzen ergeben HTTP 422.
Sortierspalten und -richtungen sind durch Enums begrenzt; Eingaben werden nicht
als SQL-Fragmente interpretiert.

Eine Datenbankmigration ist nicht erforderlich. Bestehende Typ-, Eigentümer-
und Eigentumskategorie-Indizes bleiben nutzbar. Die Teilwortsuche kann bei großen
Datenmengen einen Scan erfordern; Pagination begrenzt die Antwortgröße, ersetzt
aber keine spätere, anhand realer Last geprüfte Suchindex-Optimierung.

Die separaten Kundeninstrument- und Eigentümerhistorienendpunkte behalten ihren
bisherigen Vertrag. Clients der globalen Liste müssen zum Abruf von mehr als
100 Instrumenten nun weitere Seiten laden.
