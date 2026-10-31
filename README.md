# Atelier API – Digitale Werkstattverwaltung für Geigenbau

> **Status:** Früher Prototyp (installierte Version siehe Paketmetadaten). Die Anwendung ist **nicht produktionsreif**.
> **Pilotbetrieb:** Geigenbauwerkstatt Meister Lampe (Hildesheim).  
> **Ziel:** Papierbasierte Abläufe und verstreute Excel-Listen schrittweise durch eine sichere, schnelle und nachvollziehbare Webanwendung ersetzen.

## 1. Projektüberblick

`atelier-api` ist das FastAPI-Backend einer geplanten digitalen Atelierverwaltung für Geigenbauer. Die Anwendung soll Kunden, Instrumente, Reparaturen, Vermietungen, Übergaben, Dokumente und Zahlungen in einem gemeinsamen System abbilden. Eine browserbasierte Benutzeroberfläche für Desktop und Tablet ist geplant.

**Leitprinzip:** Jeder zusätzliche Eingabeschritt muss einen erkennbaren Nutzen haben. Die Reparaturannahme soll in wenigen Schritten möglich sein; detaillierte Instrumentendaten bleiben bei einfachen Arbeiten optional.

### Ziele

- Kunden und Instrumente schnell finden, ohne Papierordner zu durchsuchen.
- Reparatur- und Mietvorgänge von der Annahme bis zum Abschluss nachvollziehen.
- Mietverträge und Übergabeprotokolle digital erstellen und unterschreiben lassen.
- Rechnungs- und Zahlungsstände zuverlässig überblicken.
- Wiederholte Dateneingaben reduzieren, bestehende Excel-Daten kontrolliert übernehmen.
- Datensicherheit, Wiederherstellbarkeit und Datenschutz von Beginn an berücksichtigen.

### Nicht-Ziele der ersten Version

- Vollständige Finanzbuchhaltung oder ein eigenes Kassensystem.
- Eine öffentliche Instrumentendatenbank oder ein öffentliches Kundenportal.
- Eine mandantenfähige SaaS-Plattform für viele Werkstätten.
- KI-basierte Wertermittlung oder automatische Instrumentenerkennung.

## 2. Aktueller Implementierungsstand

Aktuell sind folgende Endpunkte implementiert. Alle Kunden- und Instrument-Routen
verlangen eine gültige Sitzung mit Rolle `admin` oder `employee`. Schreibende
Aufrufe benötigen zusätzlich die unten beschriebenen CSRF-Header. Root,
Health und die Anmeldemöglichkeit sind öffentlich.

| Methode | Pfad                       | Verhalten                                             |
| ------- | -------------------------- | ----------------------------------------------------- |
| `POST` | `/api/v1/auth/login` | Anmeldung und neues HttpOnly-Sitzungscookie; `200`, `401`, `403` oder `429` |
| `POST` | `/api/v1/auth/logout` | Sitzung widerrufen und Cookie löschen; `204` |
| `GET` | `/api/v1/auth/me` | Aktuelles Konto einschließlich ID, E-Mail und Rolle; `200` oder `401` |
| `GET`   | `/`                        | Gibt „Hello World“ zurück                             |
| `GET`   | `/health/live`             | Liveness-Prüfung                                      |
| `GET`   | `/health/ready`            | Prüft die Datenbankverbindung                         |
| `GET`   | `/api/v1/customers`               | Sucht Kunden mit `q`, paginiert mit `offset` und `limit` |
| `GET`   | `/api/v1/customers/{customer_id}` | Gibt einen Kunden zurück; `404` falls nicht vorhanden |
| `GET` | `/api/v1/customers/{customer_id}/overview` | Liefert Kundendetails und aktuell zugeordnete Instrumente gemeinsam; `404` bei unbekannter ID |
| `GET` | `/api/v1/customers/{customer_id}/instruments` | Liefert nur die aktuell zugeordneten Instrumente; `200` oder bei unbekanntem Kunden `404` |
| `POST`  | `/api/v1/customers`               | Legt einen Kunden an; `201` bei Erfolg                |
| `PATCH` | `/api/v1/customers/{customer_id}` | Ändert angegebene Kundendaten; `200`, bei unbekannter ID `404` |
| `DELETE` | `/api/v1/customers/{customer_id}` | Löscht einen Kunden dauerhaft; `204` ohne Inhalt, bei unbekannter ID `404` |
| `POST` | `/api/v1/instruments` | Registriert ein Instrument; `201`, bei unbekanntem Kunden `404` |
| `GET` | `/api/v1/instruments` | Liefert alle registrierten Instrumente als Liste; `200`, auch bei leerer Liste |
| `GET` | `/api/v1/instruments/{instrument_id}` | Liefert Instrumentdetails mit optionaler Kunden-ID; `200`, bei unbekannter ID `404` |
| `PATCH` | `/api/v1/instruments/{instrument_id}` | Ändert Instrumentdetails und Kundenzuordnung; `200`, bei unbekanntem Instrument oder Kunden `404` |
| `DELETE` | `/api/v1/instruments/{instrument_id}` | Löscht ein Instrument dauerhaft; `204` ohne Inhalt, bei unbekannter ID `404` |

**Aktuelles Kundenmodell:** numerische ID, Vorname, Nachname sowie optionale E-Mail-Adresse und Telefonnummer. Kundendaten können teilweise aktualisiert werden. Kunden können dauerhaft gelöscht werden.

`GET /api/v1/customers?q=maria&offset=0&limit=25` sucht nach Teiltreffern in
Vorname, Nachname, vollständigem Namen (Vorname Nachname), E-Mail und Telefonnummer.
Groß-/Kleinschreibung wird ignoriert; `%` und `_` werden wörtlich gesucht.
Telefonnummern werden in ihrer gespeicherten Schreibweise durchsucht.
Ohne `q` oder bei ausschließlich Leerzeichen werden alle nicht archivierten Kunden paginiert
aufgelistet. Ergebnisse sind nach ID aufsteigend sortiert; ohne Treffer folgt `[]`.
`offset` beginnt bei 0, `limit` ist standardmäßig 100 (erlaubt: 1–200).
Der Response-Header `X-Total-Count` enthält die Gesamtanzahl passender Kunden
vor Anwendung von `offset` und `limit`, auch bei einer leeren Seite. Der Header
ist per CORS für zugelassene Browser-Clients lesbar. Der Antwort-Body bleibt eine
Liste. Beispiel: Bei 23 Treffern liefert `offset=20&limit=10` drei Kunden und
`X-Total-Count: 23`; ab `offset=23` folgt `[]` mit derselben Gesamtanzahl.
Negative oder nicht ganzzahlige Offsets sowie Seitengrößen außerhalb von 1–200
werden mit HTTP 422 abgewiesen. Ohne Suchfilter zählt der Header alle Kunden
innerhalb des gewählten Archivfilters.
Bei gleichzeitigem Anlegen oder Löschen können Anzahl und Seite voneinander
abweichen, da sie durch zwei Abfragen ermittelt werden.
Suchbegriffe sind auf 200 Zeichen begrenzt. Der bestehende Werkstatt-Zugriffsschutz
gilt auch für die Suche.

### Validierung von Kundendaten

Bei Anlage sind nur Vorname und Nachname erforderlich. Beide werden außen von
Leerraum (auch Unicode-Leerraum) bereinigt und müssen danach 1–100 Zeichen lang
sein. Innere Leerzeichen bleiben erhalten. E-Mail und Telefon sind optional;
fehlende Angaben erscheinen als `null`. E-Mail-Adressen werden nach dem Trimmen
mit Pydantic `EmailStr` geprüft und sind auf 254 Zeichen begrenzt. Die Domain
wird normalisiert, der lokale Teil wird nicht pauschal kleingeschrieben.

Telefonangaben dürfen vor Normalisierung höchstens 64 Zeichen umfassen.
Leerzeichen, Klammern, Punkte, Schrägstriche und Bindestriche werden entfernt.
`0049 (176) 123-4567` wird beispielsweise zu `+491761234567`. Gespeichert werden
3–15 ASCII-Ziffern mit optionalem `+` (maximal 16 Zeichen); ein internationaler
Präfix darf nicht mit Null beginnen. Nationale Nummern wie `0176 1234567` bleiben
national (`01761234567`): Es wird kein Land geraten. Buchstaben und Durchwahlen
werden abgewiesen. Die Formatprüfung bestätigt weder Erreichbarkeit noch die
Zuteilung der Nummer. Telefonnummernsuche verwendet die gespeicherte Schreibweise.

Ungültige Eingaben ergeben HTTP 422, bevor Daten geschrieben werden. PostgreSQL
sichert Feldlängen, nichtleere getrimmte Namen und das normalisierte Telefonformat
zusätzlich ab. Die vollständige E-Mail-Syntaxprüfung erfolgt in der Anwendung.

Migration: `uv run alembic upgrade head` (Revision `a42d73e15b90`). Sie trimmt
vorhandene Namen und Kontaktfelder, wandelt leere Kontakte in `NULL` um und
normalisiert Telefonnummern. Ungültige Namen/Telefonnummern oder zu lange Werte
brechen die gesamte PostgreSQL-Migration ab; nichts wird abgeschnitten oder
gelöscht. Vor dem Rollout bestehende Daten und Backup prüfen, problematische
Werte fachlich korrigieren und erneut migrieren. Ein Downgrade bricht ab, solange
Kunden ohne E-Mail bestehen, da die alte Version `NOT NULL` verlangt. Bereits
normalisierte Formatierung kann durch einen Downgrade nicht rekonstruiert werden.
Diese Kundenregeln ändern nicht die weiterhin erforderliche Login-E-Mail von
Anwendungsbenutzern.

### Kundenübersicht

`GET /api/v1/customers/{customer_id}/overview` liefert ein Objekt mit `customer`
(einschließlich `is_archived`) und `instruments`. Instrumente sind nach ID
aufsteigend sortiert. Fremde und nicht zugeordnete Instrumente werden nicht
ausgegeben; ein Kunde ohne Instrumente erhält `instruments: []`. Archivierte
Kunden bleiben direkt abrufbar. Unbekannte Kunden ergeben HTTP 404, ungültige
ID-Formate HTTP 422. Nur Administratoren und Mitarbeiter haben Zugriff.

Der Endpunkt bildet aktuelle Instrumentzuordnungen ab, keine Eigentümerhistorie.
Kundendetails und Instrumente werden in zwei Datenbankabfragen gelesen;
gleichzeitige Änderungen können zwischen diesen Abfragen sichtbar werden.
Die Kundenübersicht bleibt auf Kunden- und Instrumentdaten begrenzt. Reparaturarbeiten
und Dokumente sind separat über die [Instrumenthistorie](docs/workshop-history.md)
abrufbar. Mietvertrags- und Rechnungsmodelle existieren weiterhin noch nicht.

### Kunden archivieren und wiederherstellen

`PATCH /api/v1/customers/{customer_id}/archive` mit `{"is_archived": true}`
archiviert einen Kunden; mit `{"is_archived": false}` wird er wiederhergestellt.
Nur Administratoren und Mitarbeiter dürfen diese Operation ausführen. Die
Antwort enthält den vollständigen Kunden einschließlich `is_archived` (HTTP 200).
Neue und bei der Migration vorhandene Kunden sind zunächst nicht archiviert.
Unbekannte IDs ergeben HTTP 404, ungültige Eingaben HTTP 422. Wiederholte
Zuweisungen desselben Zustands verändern nichts und erzeugen kein Audit-Ereignis.

Archivierte Kunden sind aus der Standardliste und -suche einschließlich
`X-Total-Count` ausgeschlossen. `include_archived=true` schließt sie ausdrücklich
wieder ein. Der direkte Abruf per ID bleibt möglich. Archivierung verändert weder
persönliche Daten noch Instrumentzuordnungen, Benutzerzuordnungen oder
Anmeldeberechtigungen; sie ist keine Benutzerdeaktivierung. Die Wiederherstellung
macht denselben Datensatz mit derselben ID wieder in der Standardsuche sichtbar.
Archivierung und Audit-Ereignis werden gemeinsam committet.

Archivierung ist keine Löschung und erfüllt allein keine Löschpflicht.
`DELETE /api/v1/customers/{customer_id}` bleibt eine separate, endgültige Operation
mit den bisherigen Auswirkungen auf Zuordnungen. Es gibt weder automatische
Löschung archivierter Kunden noch eine technisch hinterlegte Kunden-Aufbewahrungsfrist.
Vor einer endgültigen Löschung muss der Betreiber die betrieblich festgelegten
Aufbewahrungsanforderungen und gegebenenfalls Aufbewahrungsstopps prüfen. Die
Audit-Aufbewahrungsfrist gilt ausschließlich für das Audit-Protokoll.

Die Migration `f31b62d04a89` wird mit `uv run alembic upgrade head` eingespielt.

### Kundendaten aktualisieren

`PATCH /api/v1/customers/{customer_id}` aktualisiert nur die übergebenen Felder und liefert den vollständigen aktualisierten Kunden zurück. Die ID wird ausschließlich im Pfad angegeben. Beispiel bei laufendem Entwicklungsserver:

```bash
curl --fail-with-body -X PATCH -b /private/tmp/atelier-cookies.txt -H 'Origin: http://127.0.0.1:8000' -H 'X-CSRF-Protection: 1' http://127.0.0.1:8000/api/v1/customers/1 \
  -H 'Content-Type: application/json' \
  -d '{"first_name":"Maria","email":"maria@example.com","phone":null}'
```

Nicht angegebene Felder bleiben unverändert. `email: null` und `phone: null` entfernen die jeweilige Kontaktangabe; leere oder nur aus Leerraum bestehende Kontaktfelder werden ebenfalls als `null` gespeichert. Vorname und Nachname dürfen nicht `null` sein; Namen werden getrimmt und dürfen nicht leer sein. E-Mail-Adressen werden validiert, wenn angegeben. Unbekannte Felder (einschließlich `id`) werden mit HTTP 422 abgewiesen. Ein leerer JSON-Body `{}` liefert den vorhandenen Kunden unverändert zurück. Eine unbekannte Kunden-ID ergibt HTTP 404. Request- und Antwortschema sind unter `/docs` dokumentiert.

### Audit-Protokoll

`GET /api/v1/audit-events` bietet ausschließlich Administratoren einen gefilterten,
paginierten Lesezugriff. Fachliche Änderungen und Audit-Einträge werden gemeinsam
committet. Die Ereignisse enthalten keine Passwörter, Session-Geheimnisse oder
vollständigen Request-Bodies. Aufbewahrung (Standard: 180 Tage), Bereinigung,
implementierte Ereignisse und Integritätsgrenzen sind in [docs/audit.md](docs/audit.md)
beschrieben. Der Betreiber plant `uv run atelier-audit-cleanup` täglich ein.

### Kunden löschen

`DELETE /api/v1/customers/{customer_id}` löscht den Kunden dauerhaft aus der Datenbank. Nach erfolgreichem Commit liefert die API HTTP 204 ohne Antwortinhalt. Der Kunde erscheint nicht mehr in der Kundenliste; ein anschließender Abruf oder erneutes Löschen liefert HTTP 404 mit `Customer not found`. Ungültige ID-Formate liefern HTTP 422. Andere Kunden bleiben unverändert.

```bash
curl --fail-with-body -i -X DELETE -b /private/tmp/atelier-cookies.txt -H 'Origin: http://127.0.0.1:8000' -H 'X-CSRF-Protection: 1' http://127.0.0.1:8000/api/v1/customers/1
```

Der Endpunkt benötigt keinen Request-Body und ist unter `/docs` dokumentiert. Zugeordnete Instrumente bleiben beim Löschen eines Kunden erhalten; die Datenbank setzt deren `customer_id` auf `null`. Es werden keine Archivierung oder kaskadierenden Löschungen von Instrumenten implementiert.

### Instrumentmodell

Das Feature `atelier_api.instruments` enthält das Tabellenmodell `Instrument` sowie `InstrumentCreate`, `InstrumentRead` und `InstrumentUpdate`. `POST /api/v1/instruments` registriert Instrumente über einen validierten JSON-Request und liefert den vollständigen gespeicherten Datensatz einschließlich ID zurück.

| Feld | Bedeutung / Validierung |
| --- | --- |
| `id` | Von der Datenbank erzeugte Ganzzahl; gehört zur Ausgabe, nicht zur Eingabe |
| `type` | Pflichtfeld: `violin`, `viola`, `cello`, `double_bass` oder `bow` |
| `body_length_mm` | Optionale positive endliche Korpuslänge in mm, nur für Streichinstrumente |
| `bow_weight_g` | Optionales positives endliches Bogengewicht in g, nur für Bögen |
| `maker` | Optionaler Hersteller-/Geigenbauername |
| `year_of_manufacture` | Optionales ganzzahliges Baujahr von 1 bis 9999; unbekannt bleibt `null` |
| `identification_number` | Optionale Serien- oder Identifikationsnummer, nicht global eindeutig |
| `notes` | Optionaler Freitext |
| `customer_id` | Optionale positive Eigentümer-ID; nur bei `ownership=customer`, verweist auf einen existierenden Kunden |
| `ownership` | `customer`, `workshop` oder `unassigned`; siehe [Eigentum und Historie](docs/instrument-ownership.md) |

Nur `type` ist für die Eingabe erforderlich. Unbekannte Eingabefelder werden abgewiesen. Die Baujahrprüfung beschränkt sich auf den Zahlenbereich; eine zusätzliche Regel gegen zukünftige Jahre besteht nicht. Ohne explizite Kategorie und ohne Kunden-ID wird `unassigned` gespeichert; Werkstatteigentum wird ausdrücklich mit `ownership=workshop` gekennzeichnet. Ein Kunde kann mehrere Instrumente besitzen; `Instrument.customer` liefert die zugehörige Kundeninstanz. Kategorie- und Besitzerwechsel werden atomar in einer eigenen [Eigentümerhistorie](docs/instrument-ownership.md) gespeichert.

Die Datenbank erzwingt Typ, Baujahrbereich und gültige Kundenreferenzen. Beim Löschen eines Kunden wird die Referenz durch `ON DELETE SET NULL` aufgehoben; das Instrument und seine Detaildaten bleiben erhalten. Die Migration `a84c6e21f902` erstellt die Tabelle und den Index auf `customer_id`:

```bash
make db-migrate
make db-check
```

Ein Downgrade dieser Revision entfernt die Instrumenttabelle einschließlich ihrer Daten; die Kundentabelle bleibt erhalten.

### Werkstatthistorie eines Instruments

`GET /api/v1/instruments/{id}/history` verbindet Instrumentdetails mit
chronologisch sortierten Reparatureinträgen, Arbeitsbeschreibungen und
Dokumentmetadaten. Archivierte Reparaturen bleiben sichtbar; Dateien können
über einen eigenen geschützten Download gelesen werden. Neue Arbeiten werden
über `POST /api/v1/instruments/{id}/repair-orders` mit Beschreibung und
Reparaturzeitpunkt erfasst. Instrumente mit Reparaturhistorie sind vor endgültiger
Löschung geschützt (HTTP 409). API, Uploadgrenze, Archivierung und Migration
beschreibt [Werkstatthistorie](docs/workshop-history.md).

### Instrumente eines Kunden anzeigen

`GET /api/v1/customers/{customer_id}/instruments` liefert HTTP 200 und eine Liste nach `list[InstrumentRead]`. Die Abfrage prüft zuerst, ob der Kunde existiert, und filtert danach in PostgreSQL nach `instrument.customer_id`. Instrumente anderer Kunden und unzugeordnete Instrumente werden nicht zurückgegeben.

```bash
curl --fail-with-body -b /private/tmp/atelier-cookies.txt -H 'Origin: http://127.0.0.1:8000' -H 'X-CSRF-Protection: 1' http://127.0.0.1:8000/api/v1/customers/1/instruments
```

Ein bestehender Kunde ohne Instrumente erhält `[]`; ein unbekannter Kunde erhält HTTP 404 mit `Customer not found`. Ein ungültiges ID-Format ergibt HTTP 422. Der Endpunkt erscheint unter `/docs` im Bereich `customers`. Die Liste bildet die **aktuelle Zuordnung** ab: Nach einem Kundenwechsel erscheint das Instrument beim neuen Kunden; nach Aufheben der Zuordnung bei keinem Kunden. Frühere Zuordnungen sind separat über `/api/v1/instruments/{id}/ownership-history` abrufbar. Es gibt noch keine Pagination oder festgelegte Sortierreihenfolge.

Details, optionale Messwerte, Typwechsel und Migration sind in
[Instrumentkategorien](docs/instrument-categories.md) beschrieben.

### Instrumente auflisten

`GET /api/v1/instruments` unterstützt die optionalen UND-verknüpften Filter `type` (z. B. `bow`) und `ownership` (z. B. `workshop`) und liefert HTTP 200 und eine JSON-Liste mit dem Antwortschema `list[InstrumentRead]`. Jeder Eintrag enthält ID, Typ, Hersteller, Baujahr, Identifikationsnummer, Notizen und die optionale Kunden-ID. Unzugeordnete Instrumente werden ebenfalls angezeigt. Sind keine Instrumente vorhanden, ist die Antwort `[]`. Die Liste unterstützt `q` für Identifikationsnummern, `customer_id` für aktuelle Eigentümer, `offset`/`limit` für Pagination und `sort_by`/`sort_order` für Sortierung. Standard sind 100 Einträge nach ID aufsteigend, maximal 200; `X-Total-Count` enthält alle Treffer vor Pagination. Details stehen in [Instrumentensuche](docs/instrument-search.md). Der Endpunkt erscheint unter `/docs`.

```bash
curl --fail -b /private/tmp/atelier-cookies.txt -H 'Origin: http://127.0.0.1:8000' -H 'X-CSRF-Protection: 1' http://127.0.0.1:8000/api/v1/instruments
```

### Einzelnes Instrument abrufen

`GET /api/v1/instruments/{instrument_id}` liefert HTTP 200 mit dem Schema `InstrumentRead`: ID, Typ, Hersteller, Baujahr, Identifikationsnummer, Notizen und die zugeordnete `customer_id`. Bei Instrumenten ohne Kundenzuordnung ist `customer_id` gleich `null`. Es wird keine Kundeninstanz eingebettet. Nach dem Löschen eines zugeordneten Kunden bleibt das Instrument abrufbar und die Kunden-ID wird `null`.

```bash
curl --fail-with-body -b /private/tmp/atelier-cookies.txt -H 'Origin: http://127.0.0.1:8000' -H 'X-CSRF-Protection: 1' http://127.0.0.1:8000/api/v1/instruments/1
```

Eine unbekannte Instrument-ID liefert HTTP 404 mit `Instrument not found`; ein ungültiges ID-Format liefert HTTP 422. Der Endpunkt ist unter `/docs` dokumentiert.

### Instrument aktualisieren

`PATCH /api/v1/instruments/{instrument_id}` ändert nur die angegebenen Felder und liefert mit HTTP 200 den vollständigen aktualisierten Datensatz nach `InstrumentRead` zurück:

```bash
curl --fail-with-body -X PATCH -b /private/tmp/atelier-cookies.txt -H 'Origin: http://127.0.0.1:8000' -H 'X-CSRF-Protection: 1' http://127.0.0.1:8000/api/v1/instruments/1 \
  -H 'Content-Type: application/json' \
  -d '{"maker":"Updated maker","year_of_manufacture":1930,"customer_id":2}'
```

Nicht angegebene Felder bleiben erhalten. Eine bestehende Kunden-ID ändert die Zuordnung; `customer_id: null` entfernt sie. `maker`, `year_of_manufacture`, `identification_number` und `notes` können ebenfalls mit `null` geleert werden. `type` darf entfallen, aber nicht `null` oder ein unbekannter Instrumenttyp sein. Für Baujahr und Kunden-ID gelten dieselben Grenzen wie bei der Registrierung. Die ID selbst und unbekannte Felder sind nicht änderbar.

Ein unbekanntes Instrument ergibt HTTP 404 mit `Instrument not found`. Ein unbekannter neuer Kunde ergibt HTTP 404 mit `Customer not found`; dabei werden auch andere übergebene Änderungen nicht gespeichert. Ungültige Eingaben ergeben HTTP 422. Ein leerer JSON-Body `{}` liefert das Instrument unverändert zurück, ohne einen Commit auszuführen. Der Endpunkt ist unter `/docs` dokumentiert.

### Instrument löschen

`DELETE /api/v1/instruments/{instrument_id}` löscht ein Instrument dauerhaft und liefert nach erfolgreichem Commit HTTP 204 ohne Antwortinhalt. Die zugeordnete Kundenakte und andere Instrumente bleiben unverändert. Das gelöschte Instrument erscheint nicht mehr in `GET /api/v1/instruments`; Einzelabruf und erneutes Löschen ergeben HTTP 404 mit `Instrument not found`. Ungültige ID-Formate ergeben HTTP 422. Der Endpunkt benötigt keinen Request-Body und ist unter `/docs` dokumentiert.

```bash
curl --fail-with-body -i -X DELETE -b /private/tmp/atelier-cookies.txt -H 'Origin: http://127.0.0.1:8000' -H 'X-CSRF-Protection: 1' http://127.0.0.1:8000/api/v1/instruments/1
```

### Instrument registrieren

Nach Anwendung der Migrationen akzeptiert `POST /api/v1/instruments` beispielsweise:

```bash
curl --fail-with-body -X POST -b /private/tmp/atelier-cookies.txt -H 'Origin: http://127.0.0.1:8000' -H 'X-CSRF-Protection: 1' http://127.0.0.1:8000/api/v1/instruments \
  -H 'Content-Type: application/json' \
  -d '{"type":"violin","maker":"Example maker","year_of_manufacture":1920,"identification_number":"LABEL-42","notes":"Reparierte Decke.","customer_id":1}'
```

`customer_id` muss auf einen bereits vorhandenen Kunden verweisen. Für Werkstattbestand kann das Feld entfallen oder `null` sein. Ein unbekannter Kunde ergibt HTTP 404 mit `Customer not found`; ungültige Felder, fehlender Typ oder eine ungültige Kunden-ID wie `0` ergeben HTTP 422. Bei Erfolg wird der Datensatz vor der Antwort gespeichert und mit HTTP 201 einschließlich automatisch vergebener `id` und aller optionalen Felder zurückgegeben. Es wird kein Kunde automatisch angelegt. Request- und Antwortschema sowie Fehlerantworten sind unter `/docs` dokumentiert.


### Anwendungsbenutzer und autorisierte Verwaltung

`atelier_api.users` enthält ein persistentes, von Werkstattkunden getrenntes Kontenmodell. Es gibt keine öffentliche Registrierung und keine Benutzer-HTTP-Endpunkte.

| Feld in `app_user` | Verhalten |
| --- | --- |
| `id` | Automatisch erzeugter Integer-Primärschlüssel |
| `email` | Validierte, anwendungsseitig kleingeschriebene E-Mail; eindeutiger Datenbankindex auf `lower(email)` |
| `hashed_password` | Argon2id-Hash; kein Klartextpasswort |
| `is_active` | Aktivierungsstatus, standardmäßig `true` |
| `role` | `admin`, `employee` oder `customer`; Standard `employee` |
| `customer_id` | Optionale, eindeutige Fremdschlüsselreferenz auf `customer.id` |
| `created_at`, `updated_at` | Zeitzonenbewusste `TIMESTAMPTZ`-Werte, Ausgabe in UTC |
| `auth_version` | Interner Versionszähler zur Invalidierung alter authentifizierter Identitäten |

Die Rollen werden als `UserRole.ADMIN`, `UserRole.EMPLOYEE` und `UserRole.CUSTOMER` definiert und in der Datenbank durch einen Check-Constraint begrenzt. `UserCreate` akzeptiert weder Rolle noch Kundenzuordnung. Nur eine autorisierte Administratoroperation kann diese Werte ausdrücklich setzen. Auch Administratoren dürfen ihre eigene Rolle nicht ändern.

Passwörter werden mit `pwdlib[argon2]` und Argon2id gehasht, entsprechend der [FastAPI-Dokumentation](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/). Jeder Hash hat einen zufälligen Salt. Die Verifikation verwendet die Bibliothek und liest die Parameter aus dem gespeicherten Hash; ältere Argon2-Parameter bleiben verifizierbar. `UserCreate` akzeptiert 12 bis 1024 Zeichen als `SecretStr`, ohne Trimmen oder Abschneiden. `UserRead`, Tabellenmodell-Serialisierung und Repräsentation geben weder Passwort noch Hash aus. Validierungsfehler verbergen Eingaben und der gemeinsame Datenbank-Engine verbirgt SQL-Parameter in Logs und Exceptions.

#### Erstadministrator und weitere Konten

Vorher Migrationen anwenden:

```bash
make db-migrate
make db-check
uv run atelier-users bootstrap --email owner@example.com
```

Der Bootstrap verlangt ein interaktives Terminal und fragt das neue Passwort zweimal verdeckt ab. Es gibt keine Passwort-Argumente, hartcodierten Zugangsdaten oder automatisch angelegte Standardkonten. Der Befehl ist ein expliziter lokaler Betreiberprozess mit Datenbankzugriff. Eine gesperrte Singleton-Zeile in `user_provisioning_state` schützt vor parallelem Bootstrap und hält die einmalige Freigabe dauerhaft geschlossen, auch wenn Konten später gelöscht werden. Existierende Administratoren verhindern ebenfalls einen erneuten Bootstrap.

Alle weiteren CLI-Befehle prüfen E-Mail und Passwort eines aktiven Administrators. Neue interne Benutzer bekommen ohne explizite Rollenangabe `employee`:

```bash
uv run atelier-users create --admin-email owner@example.com --email employee@example.com
uv run atelier-users create --admin-email owner@example.com --email second-admin@example.com --role admin
uv run atelier-users deactivate 2 --admin-email owner@example.com
uv run atelier-users activate 2 --admin-email owner@example.com
uv run atelier-users set-role 2 employee --admin-email owner@example.com
uv run atelier-users associate 2 --customer-id 1 --admin-email owner@example.com
uv run atelier-users associate 2 --clear --admin-email owner@example.com
```

Der Service verlangt bei jeder Verwaltungsoperation eine frisch geprüfte Administratoridentität. Rollen werden aus dem aktuellen Datenbankdatensatz gelesen. Die letzte aktive Administratorperson kann weder deaktiviert, herabgestuft noch gelöscht werden. Verwaltungsoperationen sperren die gemeinsame Zustandszeile, damit parallele Änderungen diese Regel nicht umgehen. Zusätzlich schützt ein Datenbanktrigger den letzten aktiven Administrator bei direkten Updates und Löschungen.

#### Kundenbeziehung und Portalrolle

Kunden können ohne Benutzerkonto bestehen. Eine gleiche E-Mail erzeugt keine Zuordnung. Administratoren können eine vorhandene Kunden-ID ausdrücklich zuordnen oder entfernen; Fremdschlüssel und Unique-Constraint erlauben zunächst höchstens ein Konto pro Kunde. Weitere Konten ohne Kundenzuordnung bleiben möglich. Beim Löschen eines Kunden wird die Referenz aufgehoben; beim Löschen oder Deaktivieren eines Kontos bleiben Kunden und Instrumente erhalten.

Kundenanmeldung ist standardmäßig durch `CUSTOMER_PORTAL_AUTH_ENABLED=false`
gesperrt. Die technische Freigabe `true` erlaubt nur aktiven Konten mit
Kundenzuordnung die Anmeldung und `/api/v1/auth/me`. Auch dann bleiben interne
Kunden- und Instrument-Routen mit HTTP 403 gesperrt. Einladungen und eine
Kundenportal-Oberfläche sind noch nicht implementiert.

#### Sichere Sitzungsanmeldung

Nach `make db-migrate` und dem oben beschriebenen Benutzer-Bootstrap stehen
`POST /api/v1/auth/login`, `POST /api/v1/auth/logout` und `GET /api/v1/auth/me` bereit.
Login akzeptiert JSON mit `email` und `password`; die E-Mail wird getrimmt und
kleingeschrieben. Passwortprüfung erfolgt über Argon2id. Unbekannte E-Mail,
ungültige E-Mail, falsches Passwort, inaktive Konten und gesperrte Portalrollen
erhalten dieselbe Antwort: HTTP 401 mit `Invalid credentials`.
Fehlende oder strukturell ungültige JSON-Felder ergeben eine generische 422-Antwort.

Jede Anmeldung erzeugt einen neuen zufälligen Token aus 32 kryptographisch
zufälligen Bytes. PostgreSQL enthält ausschließlich dessen SHA-256-Verifier in
`user_session`, mit eindeutigem Index, Benutzer-Fremdschlüssel und
UTC-Zeitstempeln. Der Browser erhält den Token ausschließlich als Cookie;
Antwort-JSON und Logs enthalten weder Token noch Passwort oder Hash.
Eine erneute Anmeldung im selben Browser widerruft dessen bisherige Sitzung.
Andere Geräte behalten ihre eigenen Sitzungen.

`get_current_user` prüft bei jeder geschützten Anfrage die Sitzung sowie den
aktuellen Kontostatus und `auth_version`. Standardmäßig gelten 30 Minuten
Inaktivität und acht Stunden absolute Lebensdauer. Aktivität aktualisiert nur
`last_activity_at`, niemals `expires_at`. Abgelaufene, widerrufene oder
fehlende Cookies ergeben 401. Deaktivierung, Rollen-, Passwort- und
Kundenzuordnungsänderungen widerrufen bestehende Sitzungen auch im
Datenbanktrigger; Reaktivierung macht alte Cookies nicht wieder gültig.
Autorisierung erfolgt separat durch `require_internal_user`.

Die App prüft beim Aufbau jede FastAPI-Route. Ohne ausdrücklichen Eintrag als
öffentliche Operation muss ihre Dependency-Kette `get_current_user` enthalten;
andernfalls bricht der Start mit einem Konfigurationsfehler ab. Öffentlich sind
nur `/`, `GET /health/live`, `GET /health/ready`, Login und der idempotente,
CSRF-geschützte Logout. Dadurch werden neue Business-Router standardmäßig
abgewiesen, bis sie die zentrale Authentifizierungsabhängigkeit erhalten.
Interne Router erhalten zusätzlich zentral `require_internal_user`; die
einzelnen Customer- und Instrument-Handler duplizieren keine Rollenprüfung.
Künftige Reparatur-, Miet-, Rechnungs- und Dokumentrouter müssen auf dieselbe
Weise als interne Router registriert werden.

Logout benötigt dieselben CSRF-Header wie Login, widerruft die Sitzung in
PostgreSQL und entfernt das Cookie mit identischen Sicherheitsattributen.
Wiederholter Logout liefert weiterhin 204. Authentifizierungsantworten und
Sicherheitsfehler erhalten `Cache-Control: no-store`.

#### Umgebung, Cookies und Frontend

| Variable | Standard / Bedeutung |
| --- | --- |
| `ENVIRONMENT` | `development` lokal, im Produktivbetrieb ausdrücklich `production` setzen |
| `FRONTEND_ORIGINS` | JSON-Liste exakter erlaubter Origins; lokal localhost/127.0.0.1 mit Port 3000/8000 |
| `SESSION_IDLE_SECONDS` | `1800`, serverseitiger Inaktivitätsablauf |
| `SESSION_ABSOLUTE_SECONDS` | `28800`, absolute Lebensdauer; mindestens so lang wie der Inaktivitätsablauf |
| `LOGIN_ACCOUNT_LIMIT` | `10` Versuche pro normalisierter E-Mail und Zeitfenster |
| `LOGIN_IP_LIMIT` | `30` Versuche pro Client-IP und Zeitfenster |
| `LOGIN_WINDOW_SECONDS` | `900`, Zeitfenster für beide Login-Limits |
| `TRUSTED_PROXY_IPS` | JSON-Liste von Proxy-IP-Adressen/CIDRs, standardmäßig leer |
| `CUSTOMER_PORTAL_AUTH_ENABLED` | `false`; separates Freigabesignal für künftigen Portalzugriff |

Produktion setzt beispielsweise
`ENVIRONMENT=production` und
`FRONTEND_ORIGINS='["https://app.example.com"]'`, mit
`https://api.example.com` als API. Beide Hosts liegen unter derselben
registrierbaren Domain und verwenden HTTPS, sodass `SameSite=Lax` funktioniert.
Das Cookie heißt `__Host-session`, mit `Secure; HttpOnly; SameSite=Lax; Path=/`
und ohne `Domain`. Es bleibt ausschließlich an den API-Host gebunden.
Produktionsanfragen über HTTP werden abgewiesen; Sicherheitsattribute lassen
sich dort nicht einzeln abschalten.
Swagger UI (`/docs`), ReDoc (`/redoc`) und das öffentliche OpenAPI-Dokument
(`/openapi.json`) existieren ausschließlich in `development`. Mit
`ENVIRONMENT=production` werden alle drei Routen entfernt; die interne
`app.openapi()`-Erzeugung für Tests und Werkzeugbau bleibt verfügbar.

Für lokale HTTP-Entwicklung heißt das getrennte Cookie `dev-session` und
verzichtet auf `Secure`. Frontend und API sollten beide `localhost` oder
beide `127.0.0.1` verwenden; diese Hostnamen nicht mischen.
In Entwicklung und Produktion muss das Frontend `credentials: "include"`
verwenden. Kein Token gehört in localStorage oder sessionStorage.

Die CSRF-Strategie kombiniert **verpflichtenden exakten Origin-Abgleich** und
**verpflichtenden Custom-Header `X-CSRF-Protection: 1`** für Login, Logout und
alle schreibenden authentifizierten Anfragen. Dieser Header erzwingt bei
Cross-Origin-Anfragen einen Browser-Preflight; CORS erlaubt nur die expliziten
Origins und unterstützt Credentials. Wildcards, Origin `null` und fehlende
Header werden abgewiesen. Der Headerwert ist kein Geheimnis: Diese
[OWASP-Custom-Header-Strategie](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html#employing-custom-request-headers-for-ajaxapi)
benötigt hier keinen zusätzlichen CSRF-Token. Freigegebene Frontend-Origins
müssen vertrauenswürdig bleiben.

Beispiel für eine Frontend-Anmeldung; `email` und `password` stammen aus dem
Anmeldeformular:

```javascript
const api = "http://localhost:8000"; // Produktion: https://api.example.com
const login = await fetch(api + "/api/v1/auth/login", {
  method: "POST",
  credentials: "include",
  headers: { "Content-Type": "application/json", "X-CSRF-Protection": "1" },
  body: JSON.stringify({ email, password }),
});
if (!login.ok) throw new Error("Anmeldung fehlgeschlagen");
const me = await fetch(api + "/api/v1/auth/me", { credentials: "include" });
const logout = await fetch(api + "/api/v1/auth/logout", {
  method: "POST",
  credentials: "include",
  headers: { "X-CSRF-Protection": "1" },
});
```

Der Browser setzt `Origin` selbst. Bei curl/anderen HTTP-Clients müssen
`Origin` und der Custom-Header ausdrücklich mitgesendet und Cookies mit einer
Cookie-Jar gespeichert bzw. wiederverwendet werden. Die fachlichen curl-Beispiele
oben setzen eine zuvor erstellte Cookie-Jar `/private/tmp/atelier-cookies.txt`
voraus. Swagger zeigt die Endpunkte; für schreibende Tests im Browser muss
ebenfalls der Custom-Header gesetzt werden.

`atelier-api` vertraut standardmäßig keinen Forwarded-Headern. Hinter einem
Reverse Proxy nur dessen tatsächliche IP/Netze in `TRUSTED_PROXY_IPS` eintragen.
Der Proxy muss eingehende Forwarded-Header entfernen/überschreiben und
`X-Forwarded-For` und `X-Forwarded-Proto` selbst setzen; direkter externer
Zugriff auf den Backend-Port muss gesperrt sein. Der dokumentierte CLI-Start
übergibt die Allowlist an Uvicorn. Bei anderen ASGI-Startbefehlen ist dieselbe
explizite Proxy-Konfiguration erforderlich; niemals `forwarded-allow-ips="*"`.

#### Login-Limits und Bereinigung

PostgreSQL-Upserts zählen Versuche atomar und gemeinsam für alle API-Instanzen.
Auch erfolgreiche Versuche zählen; weder Logout noch eine neue Instanz setzen
das Limit zurück. IP- und Account-Schlüssel werden gehasht gespeichert.
Unbekannte und bekannte E-Mails erhalten dieselben Limits. Bei Überschreitung
folgen HTTP 429 und `Retry-After`. Ereignisse `auth_login_failed`,
`auth_login_throttled` und `auth_login_succeeded` ermöglichen Monitoring ohne
E-Mail, Passwort oder Token zu protokollieren.

Regelmäßig als Betreiberprozess, beispielsweise über einen stündlichen Scheduler:

```bash
uv run atelier-sessions-cleanup
```

Der Befehl verwendet `DATABASE_URL`, entfernt widerrufene, inaktive oder absolut
abgelaufene Sitzungen und veraltete Rate-Limit-Zähler und gibt nur die Anzahl
entfernter Sitzungen aus. „Inaktiv“ bedeutet hier Überschreitung des
Sitzungs-Inaktivitätszeitlimits.

Migration `d03a8f762c11` erstellt Sitzungen und Login-Zähler und erweitert den
bestehenden Widerrufstrigger. Ein Downgrade entfernt alle Sitzungen und Zähler,
erhält Benutzer und Werkstattdaten und stellt den vorherigen Trigger wieder her.
JWT, Redis, Registrierung, Passwort-Reset, MFA und eine Sitzungsverwaltung für
Endnutzer gehören nicht zum Umfang.

Die neue Migration `c91e4a702b68` baut auf `b75d90ae3214` auf. Bestehende Konten erhalten die Rolle `employee`; fehlende Zeitstempel werden mit dem Migrationszeitpunkt belegt. Kunden und Instrumente werden nicht verändert. Ein Downgrade der Erweiterung erhält E-Mail, Hash und Aktivierungsstatus, entfernt aber Rollen, Zeitstempel, Kundenzuordnungen, Widerrufsversionen und Bootstrap-Zustand. Dafür ist ein Wartungsfenster mit Invalidierung externer Sitzungen notwendig. Ein weiterer Downgrade der Basisrevision entfernt die Kontentabelle.

**Wichtige offene Befunde der Bestandsaufnahme:**

- **Hoch:** Produktivkonfiguration, HTTPS-Proxy, Backups und Betrieb müssen vor Nutzung echter Kundendaten eingerichtet und geprüft werden.
- **Mittel:** Synchrone Datenbankaufrufe innerhalb von `async def`-Routen.
- **Mittel:** Fehlende Pagination, Sortierung und stärkere Eingabevalidierung.
- **Mittel:** Eine Konfiguration für den produktiven Betrieb steht noch aus.

Die Anwendungsmodule einschließlich `customers`, `instruments` und `health` werden gemeinsam als Paket `atelier_api` ausgeliefert. Der CLI-Einstiegspunkt lautet `atelier_api.cli:main`. Die CI prüft Lint, Typen, Tests, Datenbankmigrationen sowie die Installation und Imports des gebauten Wheels in einer separaten Umgebung.

### 2.1 API-Version und Software-Releases

Die HTTP-Vertragsversion und die installierte Softwareversion sind unabhängig:

- Die aktuelle API-Version ist `v1`. Authentifizierung sowie alle fachlichen
  Customer- und Instrument-Routen liegen unter `/api/v1`. Health-Endpunkte
  bleiben als Infrastruktur-Schnittstellen unter `/health/live` und
  `/health/ready` unversioniert. Die einzelnen Feature-Router kennen den
  Versionspräfix nicht; `main.py` setzt ihn einmal über einen übergeordneten
  FastAPI-`APIRouter`.
- Die Softwareversion folgt `MAJOR.MINOR.PATCH`; maßgeblich ist der Git-Release-Tag
  `vMAJOR.MINOR.PATCH`. Hatchling mit `hatch-vcs` erzeugt daraus die dynamische
  Paketversion. FastAPI und installierte Werkzeuge lesen sie aus den Paketmetadaten. Ein Release von `0.1.0` auf `0.2.0` ändert
  deshalb nicht automatisch `/api/v1`.

Die früheren unversionierten Business-Routen werden nicht parallel angeboten.
Bestehende Clients müssen `/auth`, `/customers` und `/instruments` auf
`/api/v1/auth`, `/api/v1/customers` und `/api/v1/instruments` umstellen. Das ist
eine bewusste Vertragsmigration; doppelte Routen würden Sicherheitstests und
langfristige Abschaltung erschweren. Im Repository wurde kein separates
Frontend gefunden. Dessen API-Basis muss bei Integration ebenfalls `/api/v1`
enthalten.

Eine spätere Softwareversion `0.8.0` oder `1.4.2` bleibt bei `/api/v1`, solange
der Vertrag kompatibel erweitert werden kann. Erst eine tatsächlich
inkompatible HTTP-Vertragsänderung erhält einen neuen zentralen Router mit
`/api/v2`. V1 und V2 benötigen dann getrennte Kompatibilitätstests und eine
dokumentierte Ablösefrist; Ressourcen-Router dürfen nicht einfach global
umbenannt werden.

#### Conventional Commits und Versionsberechnung

[Python Semantic Release](https://python-semantic-release.readthedocs.io/) liest
Commits seit dem letzten `vMAJOR.MINOR.PATCH`-Tag. Die Regeln sind ausdrücklich
in `pyproject.toml` konfiguriert:

| Commit | Releasewirkung |
| --- | --- |
| `feat: add repair intake` | Minor, beispielsweise `0.1.0 → 0.2.0` |
| `fix: reject invalid owner` | Patch, beispielsweise `0.2.0 → 0.2.1` |
| `perf: reduce customer queries` | Patch |
| `docs:`, `test:`, `refactor:`, `chore:`, `ci:` | Kein Release allein |
| `feat!: replace customer contract` oder Footer `BREAKING CHANGE:` | Breaking |

Solange das Projekt in `0.x.x` ist, sind `allow_zero_version=true` und
`major_on_zero=false` gesetzt. Ein Breaking Change aus `0.1.0` wird deshalb
`0.2.0`, nicht sofort `1.0.0`. Für den ersten stabilen Vertrag wird
`major_on_zero=true` gesetzt und die Änderung ausdrücklich als Breaking Change
committed. Beispiele für gültige Nachrichten:

```text
feat(instruments): store insurance value
fix(auth): reject revoked session before data access
docs: explain Neon test database
refactor(customers): separate query service
feat(api)!: replace customer response fields
```

Releases erfolgen tagbasiert nach erfolgreicher **Attelier CI** auf `main`.
Python Semantic Release 10.7.0 berechnet die nächste Version automatisch, baut
Distributionsdateien und taggt exakt den geprüften Commit. `commit: false`
verhindert Versionscommits auf dem geschützten Branch. Release Notes und der
generierte Changelog werden im GitHub Release veröffentlicht. Ein Branch-Bypass
ist dafür nicht erforderlich; normale PR-Prüfungen bleiben unverändert.

`pyproject.toml` deklariert `dynamic = ["version"]`. `uv` verwendet den gepinnten
Hatchling-/VCS-Build-Backend; `uv.lock` fixiert weiterhin die Abhängigkeiten.
Entwicklungsstände erhalten Entwicklungsversionen. Der Release-Build erhält die
berechnete neue Version vorübergehend über `SETUPTOOLS_SCM_PRETEND_VERSION` und
prüft Wheel- und Source-Metadaten vor dem Tag-Push. Ein sauberer Release-Tag liefert
bei erneutem Build dieselbe Paketversion. Laufzeitabhängigkeiten, insbesondere
`psycopg2`, werden für den Distributionsbuild nicht installiert.

Die App `atelier-release-bot` authentifiziert Checkout und Veröffentlichung mit
einem kurzlebigen, repositorybezogenen **Contents: Read and write**-Token.
`RELEASE_APP_CLIENT_ID` und `RELEASE_APP_PRIVATE_KEY` sind verpflichtend; es gibt
keinen PAT und keinen `GITHUB_TOKEN`-Fallback. Der normale Job-Token hat nur
Leserechte. Workflow- und SHA-Prüfungen schließen PR-/Fork-Code sowie veraltete
CI-Stände aus. Da Releases keine Branch-Commits erzeugen und die CI keine
Tag-Pushes abonniert, entstehen keine rekursiven Releases.

Die read-only Diagnose ergab für das aktive `main`-Ruleset keine Bypass-Akteure.
Das erklärt den früheren GH013-Fehler trotz App-Authentifizierung. Die gewählte
Architektur pusht überhaupt nicht auf `main`; etwaige Tag-Regeln müssen weiterhin
das Anlegen der Release-Tags durch die App erlauben.

Installierte Version prüfen:

```bash
uv run python -c 'from atelier_api.version import software_version; print(software_version())'
```

Lokale Versionsberechnung ohne Veröffentlichung:

```bash
uv run semantic-release --noop version --print
```

Strategievergleich, Konfiguration, Sicherheitsgrenzen, erster Release,
Render-/Neon-Deployment und Rollback sind in [docs/releases.md](docs/releases.md)
beschrieben. Ein Merge dieser Konfiguration kann nach erfolgreicher CI den ersten
echten Release auslösen; deshalb nur in einem freigegebenen Releasefenster mergen.

## 3. Geplanter Funktionsumfang

Kennzeichnung: **MVP** = für den ersten nutzbaren Pilotablauf vorgesehen; **Phase 2/3** = spätere Erweiterung. Alle folgenden Funktionen sind **geplant**, sofern nicht ausdrücklich unter Abschnitt 2 als vorhanden bezeichnet.

### 3.1 Kundenverwaltung — MVP

- Kunden anlegen, anzeigen, bearbeiten und suchen; optional archivieren statt unkontrolliert löschen.
- Privatpersonen sowie Schulen, Orchester und andere Institutionen berücksichtigen.
- Kontaktdaten, Anschrift, Notizen und eindeutige interne Kundennummer.
- Übersicht aller zugeordneten Instrumente, Reparaturen, Mietverträge und Dokumente.
- E-Mail **nicht pauschal als Pflichtfeld** voraussetzen; konkrete Pflichtfelder fachlich festlegen.
- Excel-/CSV-Import mit Vorschau, Feldzuordnung, Validierung und Duplikatprüfung.
- Nachvollziehbare Änderungen an wichtigen Stammdaten.

### 3.2 Instrumenten- und Bogenverwaltung — MVP

- **Kundeninstrumente** und **Werkstattbestand** in einem gemeinsamen fachlichen Modell unterscheiden.
- Instrumenttypen: Geige, Bratsche, Cello, Kontrabass; Bögen mit passenden zusätzlichen Merkmalen.
- Interne Instrumenten-ID; Typ und kurze Beschreibung genügen für eine schnelle Ersterfassung.
- Optional: Hersteller/Geigenbauer, Baujahr, Größe/Mensur, Kennzeichnungen, Fotos, Zustand, Herkunft und Dokumente.
- Eigentümer, Besitzer, Standort und Bestandssituation sauber unterscheiden; Eigentümerwechsel historisieren, sofern benötigt.
- Instrumentenbezogene Reparatur- und Übergabehistorie.
- Keine Pflicht zur rückwirkenden Erfassung sämtlicher Kundeninstrumente: schrittweise bei neuen Vorgängen übernehmen.
- QR-Code für **interne Identifikation**; keine personenbezogenen Daten direkt im Code. Bei wertvollen Instrumenten abnehmbare Anhänger statt Aufkleber auf dem Lack verwenden.

### 3.3 Reparaturaufträge — MVP

- Kunde und Instrument auswählen oder im selben Ablauf neu erfassen.
- Annahmedatum, Fehlerbeschreibung, geplante Arbeiten, geschätzter Preis, gewünschter Termin und Notizen erfassen.
- Zustands- und Fotodokumentation bei Bedarf.
- Status: `angenommen`, `wartet_auf_freigabe`, `in_arbeit`, `wartet_auf_material`, `abholbereit`, `abgeschlossen`, `storniert`.
- Reparaturpositionen, Arbeitszeit und Material dokumentieren; wiederkehrende Arbeitsvorlagen vorsehen.
- PDF-Annahmebeleg und Abhol-/Übergabenachweis erstellen.
- Dashboard mit offenen, überfälligen und abholbereiten Aufträgen.
- Rechnungsentwurf aus erfassten Leistungen erzeugen (Phase 2, falls nicht für den Pilot nötig).

### 3.4 Mietinstrumente, Mietverträge und Übergaben — MVP/Pilotpriorität

- Verfügbarkeit des Werkstattbestands: `verfügbar`, `vermietet`, `reserviert`, `in_wartung`, `verkauft` (fachlich noch abzustimmen).
- Vermietete Sets aus Instrument, Bogen, Kasten und Zubehör erfassen.
- Mietbeginn, Konditionen, Zahlungsintervall, Kaution und ggf. Vertragsende speichern.
- Mietvertrag aus einer **von Herrn Lampe freigegebenen Vorlage** als PDF erzeugen.
- Separates Übergabeprotokoll mit Gegenständen, Zustand, Fotos und Datum.
- Unterschrift auf Tablet/Touchscreen erfassen und dem **konkreten unveränderten Dokument** zuordnen; Zeitpunkt und Dokument-Hash protokollieren.
- Rückgabe mit Zustandsvergleich und Abschlussprotokoll dokumentieren.
- Instrumentenwechsel bei wachsenden Schülern historisieren.
- Vertragsänderungen, Kündigungen und ggf. Mietkauf-/Anrechnungsregeln erst nach Klärung der tatsächlichen Geschäftspraxis ergänzen.

**Rechtlicher Hinweis:** Eine auf dem Bildschirm gezeichnete Unterschrift ist in der Regel eine _einfache elektronische Signatur_, keine qualifizierte elektronische Signatur. Vor echtem Einsatz sind Vertragsvorlagen, Formklauseln, Beweis- und Aufbewahrungsanforderungen fachlich/rechtlich zu prüfen. Eine Unterschriftgrafik allein ist kein hinreichender Audit-Nachweis.

### 3.5 Rechnungen und Zahlungen — Phase 2 (Status früh nutzbar machen)

- Rechnungen mit Positionen, eindeutiger Nummer, Fälligkeit und Kundenbezug verwalten.
- Status aus tatsächlichen Zahlungen ableiten: `entwurf`, `offen`, `teilweise_bezahlt`, `bezahlt`, `überfällig`, `storniert` (Statusmodell noch zu präzisieren).
- Barzahlungen und Banküberweisungen **manuell** erfassen; Teilzahlungen und Korrekturen unterstützen.
- Zahlungsübersicht mit Fälligkeiten und offenen Beträgen.
- Erinnerungsvorschläge und später regelbasierter E-Mail-Versand mit Freigabe-/Sperrmöglichkeit; keine Mahnung bei ungeklärtem Zahlungseingang.
- **Optional Stripe:** Onlinezahlung über Zahlungslink; verifizierte Webhooks und idempotente Verarbeitung für automatische Zahlungszuordnung. Stripe ist **kein Ersatz** für die Erfassung von Barzahlungen oder den Bankabgleich.
- Rechnungs- und E-Rechnungspflichten in Deutschland sowie steuerliche Sonderfälle **vor produktiver Rechnungsstellung** mit fachkundiger Stelle prüfen; gegebenenfalls Integration in bestehende Buchhaltungssoftware statt Eigenentwicklung.

### 3.6 Dokumente, Suche und Benachrichtigungen — MVP/Phase 2

- Dokumente und Fotos Kunden, Instrumenten, Aufträgen oder Verträgen zuordnen.
- PDF-Generierung, kontrollierter Download und E-Mail-Versand.
- Suchfunktion über Kunden, Instrumentennummern und Aufträge.
- Später: Kundenbenachrichtigung bei „abholbereit“, Erinnerungen an Mietfälligkeiten, optionale QR-Statusseite ohne Offenlegung interner Daten.
- OCR und erweiterte Berichte nur bei nachgewiesenem Nutzen.

## 4. Kernabläufe

### Reparaturannahme

`Kunde suchen → Instrument auswählen/kurz erfassen → Auftrag und Zustand dokumentieren → Annahmebeleg → Bearbeitung/Status → Abholung → ggf. Rechnung/Zahlung`

### Vermietung

`Kunde suchen → verfügbares Instrument/Set wählen → Mietkonditionen → Mietvertrag erzeugen → Übergabeprotokoll + Fotos → digitale Signatur → Zahlungen/Fälligkeiten → Wechsel oder Rückgabe`

### Zahlungsüberwachung

`Rechnung erstellen → Fälligkeit überwachen → Zahlung manuell oder über verifizierten Zahlungsanbieter verbuchen → offenen Restbetrag berechnen → ggf. Erinnerung nach Prüfung`

## 5. Technologiestack

| Bereich                    | Stand/Plan                                                                     |
| -------------------------- | ------------------------------------------------------------------------------ |
| Python                     | ≥ 3.14 (bestehendes Projekt)                                                   |
| API                        | FastAPI                                                                        |
| Datenmodelle/Validierung   | SQLModel, Pydantic                                                             |
| Persistenz                 | PostgreSQL, SQLAlchemy (derzeit synchron)                                      |
| Migrationen                | Alembic                                                                        |
| Paket-/Umgebungsverwaltung | uv, Lockfile                                                                   |
| Tests/Qualität             | pytest, Ruff, mypy                                                             |
| CI                         | GitHub Actions                                                                 |
| Frontend                   | Geplante responsive Weboberfläche; React/TypeScript **noch nicht entschieden** |
| PDF/Signatur               | Bibliotheken und Verfahren noch auszuwählen                                    |
| Onlinezahlungen            | Stripe optional, noch nicht integriert                                         |

### Architektur und Verzeichnisstruktur

Die verbindlichen Regeln für Feature-Module, gemeinsame Dependencies, Services und Imports stehen in [Modulstruktur und Architektur](docs/architecture.md). Neue Features folgen dem dort beschriebenen Muster.

Der Datenfluss ist `HTTP/JSON → Authentifizierung/Autorisierung → FastAPI-Router → Datenbank-Session → SQLModel/SQLAlchemy → PostgreSQL`.

```text
src/atelier_api/
├── main.py           # FastAPI-App und Registrierung der Router
├── cli.py            # Startbefehl atelier-api (Uvicorn)
├── settings.py       # Konfiguration aus Umgebung und .env
├── database.py       # Engine und Session pro Anfrage
├── customers/        # Kunden-Router, API-Schemas und Tabellenmodell
├── instruments/      # Instrument-Router, Tabellenmodell und Schemas
├── users/            # Benutzer, Passwort-Hashing und Aktivierungsservice
├── auth/             # Sitzungen, Login, CSRF und Rollenabhängigkeiten
└── health/           # Liveness und Datenbank-Readiness
alembic/              # Migrationskonfiguration und versionierte Schemaänderungen
tests/                # API- und Schema-Tests
scripts/              # Prüfung des installierten Wheels
.github/workflows/    # CI-Prüfungen
```

`CustomerCreate` validiert Eingaben, `CustomerRead` beschreibt Antworten und `Customer` bildet die Datenbanktabelle ab. Die Kunden-Router verwenden synchrone SQLModel-Sessions über FastAPI-Dependencies. Alembic erstellt und verändert das Schema; der Server legt Tabellen beim Start nicht automatisch an. Eine Benutzeroberfläche ist noch nicht enthalten.

## 6. Vorgeschlagenes fachliches Datenmodell

Aktuell besteht die optionale Beziehung `Customer 1 → n Instrument` über `instrument.customer_id`. Die folgende umfangreichere Skizze mit Eigentumshistorie ist **kein vorhandenes Datenbankschema**, sondern eine Planung:

```text
Customer ──< InstrumentOwnership >── Instrument
   │                                  │
   ├──< RentalContract ──< RentalItem >┘
   │           ├──< HandoverProtocol
   │           └──< RentalCharge / Payment
   │
   └──< Invoice ──< InvoiceItem
                         └──< PaymentAllocation

Instrument ──< RepairOrder ──< RepairOrderItem
     │               │
     └──< Document   └──< Document

User ──< AuditEvent
```

Wichtige Regeln:

- Kunden können mehrere Instrumente besitzen; Instrumente können den Eigentümer wechseln.
- Reparaturaufträge gehören zu einem Instrument und haben eine eigene Historie.
- Mietverträge beziehen sich auf ein oder mehrere Mietobjekte/Zubehörteile; Wechsel sind nachvollziehbar.
- Rechnungen und Zahlungen sind getrennte Objekte, um Teilzahlungen abzubilden.
- Unterschriebene Dokumentversionen werden unveränderbar referenziert; Korrekturen erzeugen neue Versionen.
- Löschen/Archivieren, Aufbewahrung und personenbezogene Daten benötigen definierte Regeln.

## 7. Entwicklungsplan

### Phase 0 – Fundament absichern (vor echten Daten)

- [x] Wheel-Paketierung korrigieren und Installation aus gebautem Wheel testen.
- [x] CLI-Einstiegspunkt reparieren.
- [x] Lokale Einrichtung, Migrationen und Testausführung dokumentieren.
- [x] Sitzungsanmeldung und Zugriffsschutz für interne Werkstattdaten implementieren.
- [x] PostgreSQL-Integrationstests für Kunden und Migrationen mit isolierten Testdaten einrichten.
- [ ] Backup-, Restore- und Fehlerprotokollierungsstrategie festlegen.
- [ ] Datenbankzugriff konsistent gestalten (z. B. synchrone Routen bei synchronem Treiber).

### Phase 1 – Erster nutzbarer Werkstatt-Pilot

- [ ] Kunden-CRUD, Suche, Pagination und Validierung.
- [ ] Excel-/CSV-Import mit Vorschau.
- [ ] Instrumenten-/Bogenverwaltung mit Schnellanlage.
- [ ] Reparaturaufträge, Status und Dashboard.
- [ ] Dokument-/Fotoupload und PDF-Annahmebelege.
- [ ] Mietbestand und Mietvertrags-/Übergabegrundlagen.
- [ ] Digitale Unterschrift an konkrete Dokumentversion binden.
- [ ] Interne QR-Codes.
- [ ] Bedienbare Weboberfläche auf Desktop und Tablet.
- [ ] Pilot mit **synthetischen Testdaten**, anschließend kontrollierte Freigabe.

### Phase 2 – Zahlungs- und Mietprozesse vervollständigen

- [ ] Rückgaben, Instrumentenwechsel, Mietfälligkeiten.
- [ ] Rechnungsentwürfe, Zahlungen, Teilzahlungen, Statusübersicht.
- [ ] Erinnerungsworkflow und E-Mail-Versand.
- [ ] Optional Stripe-Integration.
- [ ] Rechtlich/steuerlich geprüfte Rechnungs- bzw. Buchhaltungsanbindung.

### Phase 3 – Nur bei echtem Bedarf

- [ ] Verkaufs-/Kommissionsbestand.
- [ ] Kundenstatusportal und Benachrichtigungen.
- [ ] Materiallager, Berichte, OCR, erweiterte QR-Instrumentenpässe.

## 8. Einrichtung und lokale Entwicklung

### Voraussetzungen

- Git, `make` und [uv](https://docs.astral.sh/uv/getting-started/installation/).
- Python 3.14 gemäß `.python-version`; `uv python install` installiert die passende Version.
- PostgreSQL 17, wie in der CI, sowie die PostgreSQL-Clientprogramme (`psql`, `createuser`, `createdb`). Alternativ kann die Datenbank in Docker laufen.
- Ein C-Compiler und PostgreSQL-Entwicklungsdateien mit `pg_config` im `PATH`: Die aktuelle Abhängigkeit `psycopg2` kann aus Quellcode gebaut werden. Unter macOS liefern Xcode Command Line Tools den Compiler; unter Debian/Ubuntu sind typischerweise `build-essential` und `libpq-dev` erforderlich.

### 8.1 Repository und Python-Umgebung

```bash
git clone https://github.com/CH4692/atelier-api.git
cd atelier-api
uv python install
uv sync --locked --dev
```

Alle folgenden Projektbefehle werden im Verzeichnis mit `pyproject.toml` und `Makefile` ausgeführt. `uv sync` erstellt `.venv` und installiert die im Lockfile festgelegten Abhängigkeiten. Eine manuelle Aktivierung der Umgebung ist bei `uv run` und den Make-Befehlen nicht erforderlich.

### 8.2 PostgreSQL einrichten

Für die lokale Entwicklung wird Neon im Projekt `atelier`, Branch `dev`, verwendet. Die Anwendungsdatenbank bleibt für Entwicklungsdaten erhalten. Für Tests wird im selben Branch eine getrennte Datenbank `atelier_test` verwendet. Die Verbindungen werden einmalig in `.env` gespeichert; weder ein lokaler PostgreSQL-Server noch ein erneuter Export vor jedem Testlauf sind dann erforderlich. Für Migrationen und Tests die direkte Neon-Verbindung ohne `-pooler` wählen und die TLS-Parameter beibehalten.

Die folgenden lokalen Installations- und Docker-Befehle sind Alternativen; die GitHub-CI verwendet weiterhin ihren eigenen PostgreSQL-Container.

Für eine bereits installierte und laufende lokale PostgreSQL-Instanz: Als PostgreSQL-Administrator einen Benutzer und zwei getrennte Datenbanken anlegen. Bei einer Installation mit dem Administratorkonto `postgres`:

```bash
createuser -h localhost -U postgres --pwprompt atelier
createdb -h localhost -U postgres --owner=atelier atelier
createdb -h localhost -U postgres --owner=atelier atelier_test
```

`--pwprompt` fragt das neue Passwort für `atelier` ab. Falls die lokale Installation einen anderen Administrator verwendet, `-U postgres` entsprechend ersetzen. Die Anwendung benötigt keine Superuser-Rechte.

Alternativ eine eigene Entwicklungsdatenbank mit Docker starten:

```bash
docker run --name atelier-postgres \
  -e POSTGRES_USER=atelier \
  -e POSTGRES_PASSWORD=atelier_local \
  -e POSTGRES_DB=atelier \
  -p 127.0.0.1:5432:5432 \
  -v atelier-postgres-data:/var/lib/postgresql/data \
  -d postgres:17

# Wiederholen, bis PostgreSQL Verbindungen akzeptiert:
docker exec atelier-postgres pg_isready -U atelier -d atelier

# Separate Testdatenbank anlegen (einmalig):
docker exec atelier-postgres createdb -U atelier -O atelier atelier_test
```

Die Docker-Zugangsdaten sind ausschließlich für die lokale Entwicklung gedacht. Port 5432 muss frei sein. Der Container behält die Daten im benannten Volume; spätere Starts erfolgen mit `docker start atelier-postgres`, Stoppen mit `docker stop atelier-postgres`. Die `POSTGRES_*`-Werte initialisieren nur ein leeres Datenverzeichnis und ändern keine bestehenden Benutzerpasswörter.

### 8.3 Umgebungsvariablen

```bash
cp .env.example .env
```

Die Vorlage enthält Neon-Platzhalter. In einer vorhandenen `.env` die echten Werte lokal behalten und die separate Testverbindung ergänzen:

```dotenv
DATABASE_URL='postgresql+psycopg://ROLE:PASSWORD@YOUR-ENDPOINT.neon.tech/neondb?sslmode=require&channel_binding=require'
TEST_DATABASE_URL='postgresql+psycopg://ROLE:PASSWORD@YOUR-ENDPOINT.neon.tech/atelier_test?sslmode=require&channel_binding=require'
```

| Variable | Pflicht | Bedeutung |
| --- | --- | --- |
| `DATABASE_URL` | Ja | Verbindung der Anwendung und Alembic zur Entwicklungsdatenbank. |
| `TEST_DATABASE_URL` | Für Integrationstests | Direkte PostgreSQL-Verbindung zur separaten Datenbank mit Endung `_test`. Wird nicht als Anwendungsdatenbank verwendet. |

`postgresql+psycopg` wählt den Psycopg-3-Treiber. Hostname und Datenbankname stammen aus der Neon-Verbindungsanzeige. Neon-Branch und PostgreSQL-Datenbank sind unterschiedliche Objekte. Die Testdatenbank muss tatsächlich angelegt sein; eine reine Änderung des URL-Pfades reicht nicht. Sonderzeichen im Benutzer oder Passwort müssen in der URL prozentkodiert werden, beispielsweise `@` als `%40`.

Die Anwendung und Alembic lesen `.env` relativ zum aktuellen Arbeitsverzeichnis. Bereits exportierte Umgebungsvariablen überschreiben die Werte aus `.env`. Die lokale `.env` ist in Git ignoriert; eigene Zugangsdaten gehören nicht ins Repository. Die `POSTGRES_*`-Variablen des Docker-Beispiels konfigurieren den Datenbankcontainer und werden von der API selbst nicht gelesen.

Die zentralen Settings validieren die URL-Syntax und den SQLAlchemy-Dialekt; PostgreSQL-URLs müssen einen Datenbanknamen enthalten. Konfigurationsfehler zeigen den eingegebenen Wert nicht an. Diese Prüfung baut keine Verbindung auf und prüft weder Passwort noch Erreichbarkeit.

Auch lokale Varianten wie `.env.test` sind in Git ignoriert; automatisch geladen wird ausschließlich `.env`. Andere Konfigurationen über die Umgebung bereitstellen. Nur `.env.example` wird als Vorlage versioniert. Falls echte Zugangsdaten versehentlich eingecheckt wurden, müssen sie ersetzt werden: `.gitignore` entfernt sie nicht aus der Historie.

### 8.4 Datenbankmigrationen

Vor dem ersten Start und nach dem Übernehmen neuer Migrationen:

```bash
make db-migrate
```

Das führt `uv run alembic upgrade head` aus und legt beim ersten Mal die Kundentabelle an.

| Zweck | Befehl |
| --- | --- |
| Alle ausstehenden Migrationen anwenden | `make db-migrate` |
| Aktuellen Revisionsstand anzeigen | `uv run alembic current` |
| Modelle mit dem migrierten Schema vergleichen | `make db-check` |
| Nach einer Modelländerung eine Migration erzeugen | `make db-migration message="describe change"` |
| Letzte Migration zurücknehmen | `make db-downgrade` |

Automatisch erzeugte Dateien unter `alembic/versions/` vor dem Anwenden prüfen und zusammen mit der Modelländerung committen. Ein Downgrade kann Daten löschen; die initiale Migration entfernt beim Zurücknehmen die gesamte Kundentabelle.

Anwendung sowie Online- und Offline-Migrationen verwenden dieselbe `DATABASE_URL` aus `atelier_api.settings`. In `alembic.ini` wird keine zweite Verbindungs-URL gepflegt. Offline lässt sich SQL ohne laufende Datenbank erzeugen:

```bash
uv run alembic upgrade head --sql > migration.sql
```

Dieser Befehl führt das SQL nicht aus. Die Ausgabe vor einer manuellen Anwendung prüfen. Migrationen vor dem Serverstart anwenden; die Anwendung erstellt Tabellen nicht automatisch. Bei einem Online-Verbindungsfehler beendet Alembic den Befehl mit einem Fehlerstatus und einem verständlichen Hinweis auf `DATABASE_URL` und die Datenbankerreichbarkeit, ohne Zugangsdaten auszugeben.

### 8.5 Entwicklungsserver starten

```bash
make dev
```

Dies startet `uv run fastapi dev` mit automatischem Neuladen bei Codeänderungen. Der Einstiegspunkt `atelier_api.main:app` ist in `pyproject.toml` konfiguriert.

Alternativ über den CLI-Befehl ohne automatisches Neuladen:

```bash
uv run atelier-api --host 127.0.0.1 --port 8000
uv run atelier-api --help
```

Server mit `Ctrl+C` beenden. Nach Installation des Wheels und Aktivierung seiner Umgebung ist derselbe Aufruf direkt als `atelier-api` verfügbar.

| Adresse | Zweck |
| --- | --- |
| http://127.0.0.1:8000/docs | Interaktive API-Dokumentation |
| http://127.0.0.1:8000/openapi.json | OpenAPI-Schema |
| http://127.0.0.1:8000/health/live | Liveness: `{"status":"ok"}` |
| http://127.0.0.1:8000/health/ready | Datenbankverbindung: `{"status":"ok","database":"connected"}` |

```bash
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
```

### 8.6 Tests, Lint und Typprüfung

Die verbindlichen Python-, Docstring- und API-Dokumentationsregeln stehen in [AGENTS.md](AGENTS.md). Code-Dokumentation verwendet Englisch und Google-Style-Docstrings; Ruff prüft deren Format und sinnvolle Abschnittsstruktur. Historische Migrationen werden nicht für Formatierungsänderungen umgeschrieben. Die initiale Revision enthält ausschließlich eine Importkorrektur für die Typprüfung; Schema und erzeugtes SQL bleiben unverändert.

Nach `uv sync --locked --dev` lassen sich alle Tests mit einem Befehl ausführen:

```bash
make test
# Gleichwertig: uv run pytest
```

pytest lädt `.env` automatisch vor dem Anwendungsimport. Exportierte Variablen haben Vorrang, sodass die CI ihre Container-Verbindungen verwendet. Lokal werden die Neon-Verbindungen aus `.env` genutzt. Die bisherigen fachlichen API-Tests isolieren die Anmeldung über einen Test-Override; die Authentifizierungstests nutzen eine eigene App ohne diesen Override. Die isolierten API-Tests verwenden gemockte Sessions; echte Datenbankoperationen laufen über `TEST_DATABASE_URL`. Nur bei vollständig fehlender `DATABASE_URL` in Umgebung und `.env` gibt es noch eine SQLite-Adresse zur Initialisierung. Vorhandene Dependency-Overrides werden nach jedem Test wiederhergestellt.

Mit `TEST_DATABASE_URL` in `.env` führt der folgende Befehl automatisch auch alle PostgreSQL-Integrationstests aus:

```bash
make test
```

Die in `.env` angegebene Testdatenbank muss bereits existieren. Die Integrationstest-Fixtures wenden Migrationen selbst in einem neuen Schema an; ein manuelles `make db-migrate` ist dafür nicht erforderlich.

| Abdeckung | Testdateien |
| --- | --- |
| Liveness und Readiness, einschließlich Datenbankfehlern | `tests/health/test_api.py`, `tests/integration/test_health.py` |
| Kunden anlegen, auflisten und anhand der ID abrufen | `tests/customers/test_api.py`, `tests/integration/test_customers.py` |
| Kunden teilweise ändern, Speicherung prüfen und Felder erhalten | Dieselben API-Tests und PostgreSQL-Lebenszyklustest |
| Kunden löschen, erneuter Abruf, Erhalt anderer Kunden | Dieselben API- und Integrationstests |
| Ungültige Eingaben und unbekannte IDs (422 / 404) | API-, Schema- und Integrationstests |

#### Instrumentverwaltung gezielt testen

```bash
make test-instruments
```

Der Befehl führt die API- und Schema-Tests unter `tests/instruments/` sowie die PostgreSQL-Instrument- und Zuordnungstests aus. Die Neon-Testverbindung wird wie bei `make test` aus `.env` geladen. Die CI verwendet weiterhin `make test` und nimmt neue Testdateien automatisch mit auf.

| Abnahmekriterium | Vorhandene Testabdeckung |
| --- | --- |
| Instrument anlegen | Alle Instrumenttypen, automatisch erzeugte ID, vollständige Details, mit und ohne Kunde |
| Instrumente auflisten | Schema-konforme Liste gespeicherter Instrumente und leere Liste |
| Einzelnes Instrument abrufen | Gespeicherte Details mit Kunden-ID oder `null` |
| Instrument aktualisieren | Teilupdates, unveränderte ausgelassene Felder, neue/entfernte Kundenzuordnung, Persistenz |
| Instrument löschen | 204 ohne Inhalt, anschließend 404 und aus Listen entfernt; andere Daten bleiben erhalten |
| Kunden-/Instrumentbeziehung | Mehrere Instrumente pro Kunde, Trennung von Kundenlisten, Zuordnungswechsel, ungültige Fremdschlüssel |
| Ungültige Eingaben | Fehlende/ungültige Felder, JSON-Objekt erforderlich, fehlerhaftes JSON, unveränderte Daten nach Ablehnung |
| 404-Fälle | Unbekannte Instrumente/Kunden sowie Abruf, Update und erneutes Löschen nach einer Löschung |

`tests/integration/test_instrument_lifecycle.py` verbindet Registrierung, Listen, Einzelabruf, Änderung, Kundenzuordnung und Löschung in einem durchgängigen Datenbanktest. `tests/instruments/test_request_errors.py` ergänzt ungültige JSON-Requestformen und simulierte Commit-Fehler: Ein fehlgeschlagener Schreibvorgang muss 503 statt eines Erfolgsstatus liefern und darf keine internen Fehlerdetails offenlegen. Die Anwendung selbst wird durch dieses Testticket nicht geändert.

#### PostgreSQL-Integrationstests

`TEST_DATABASE_URL` muss in `.env` oder der Umgebung gesetzt werden und auf eine PostgreSQL-Datenbank zeigen, deren Name auf `_test` endet. Die Datenbank muss bereits existieren; der Benutzer benötigt Rechte zum Erstellen und Löschen eigener Schemas. Niemals eine Produktionsdatenbank verwenden.

```bash
uv run pytest tests/integration -v
```

Ohne `TEST_DATABASE_URL` werden nur die Integrationstests mit einem Hinweis übersprungen. Eine gesetzte, aber ungeeignete URL oder nicht erreichbare Testdatenbank führt zu einem Fehler. `TEST_DATABASE_URL` wird ausschließlich von den Test-Fixtures gelesen. Die allgemeine `DATABASE_URL` wird ebenfalls aus `.env` geladen; außerhalb von pytest bleibt sie für die Anwendung erforderlich. Bei einer konfigurierten, aber nicht erreichbaren Neon-Testdatenbank wird ein Fehler gemeldet; es gibt keinen automatischen Wechsel auf eine lokale Datenbank.

Jeder Testlauf erzeugt ein Schema mit zufälligem Namen und wendet darin `alembic upgrade head` auf ein leeres Schema an; `create_all()` wird nicht verwendet. Geprüft werden der erreichte Migrationsstand, die Kundentabelle, Health-Readiness sowie der vollständige Ablauf Anlegen → Auflisten/Abrufen → Ändern → Löschen. Frische Sessions bestätigen die gespeicherten Daten; zusätzliche Fälle prüfen optionale Telefonnummern, ungültige Eingaben und fehlende Kunden.

Jeder API-Aufruf erhält eine eigene Session mit Savepoint innerhalb einer äußeren Testtransaktion. Am Testende wird die äußere Transaktion zurückgerollt, auch wenn der Endpunkt `session.commit()` aufgerufen hat. Eine zusätzliche Prüfung bestätigt nach jedem Test, dass keine Kunden- oder Instrumentdaten zurückbleiben. Am Ende des Testlaufs wird ausschließlich das eigens erzeugte Schema entfernt. Die Suite ist für sequenzielle Ausführung eingerichtet.

Die Tests in `tests/instruments/test_customer_api.py` und `tests/integration/test_customer_instruments.py` prüfen die Kundeninstrumentliste, einschließlich Filterung nach Kunde, unzugeordneter Instrumente, leerer Ergebnisse, unbekannter Kunden und Zuordnungswechsel. Die übrigen Tests unter `tests/instruments/` validieren Instrument-Schemas sowie die POST-, GET-, PATCH- und DELETE-Endpunkte einschließlich leerer Listen, Validierungsfehlern und unbekannten Kunden. `tests/integration/test_instrument_api.py` prüft Registrierung, Änderung und Löschung über HTTP, das erneute Lesen aus PostgreSQL über eine frische Session sowie den Erhalt anderer Instrumente und der Kundenakte nach einer Instrumentlöschung. `tests/integration/test_instruments.py` prüft die Speicherung aller Instrumentfelder, die Kundenzuordnung, mehrere Instrumente pro Kunde, ungültige Fremdschlüssel und Datenbankwerte sowie den Erhalt von Instrumenten beim Löschen eines Kunden. Nach jedem Test wird zusätzlich geprüft, dass keine Instrumentdaten zurückbleiben.

| Make-Befehl | Direkter Aufruf |
| --- | --- |
| `make test` | `uv run pytest` |
| `make test-instruments` | Instrument-API-, Schema- und PostgreSQL-Tests |
| `make lint` | `uv run ruff check .` |
| `make lint-fix` | `uv run ruff check . --fix` (ändert Dateien) |
| `make typecheck` | `uv run mypy .` |
| `make format-check` | `uv run ruff format --check .` |
| `make format` | `uv run ruff format .` (ändert Dateien) |

`tests/integration/test_auth.py` prüft die echte PostgreSQL-Sitzungsanmeldung
einschließlich Rollen, generischer Fehler, Cookie-Attribute, Rotation,
Inaktivitäts- und Absolutablauf, Logout/Replay, Kontoänderungen, CSRF, exaktem
CORS und instanzübergreifenden Rate-Limits. Sitzungen und Login-Zähler werden
wie Werkstattdaten je Test zurückgerollt und auf vollständige Bereinigung geprüft.
Ein gezielter Lauf: `uv run pytest tests/integration/test_auth.py`.

Die GitHub-Actions-CI startet PostgreSQL 17 für Tests und Migrationsprüfungen und wendet Migrationen vor den Tests an. Der Test-Job setzt `TEST_DATABASE_URL` und führt mit `make test` alle Tests einschließlich der Integrationstests aus; deren Fixtures prüfen zusätzlich Migrationen in einem leeren Schema. Ein eigener Job baut und installiert das Wheel in einer frischen Umgebung und prüft die Anwendung außerhalb des Quellcodeverzeichnisses.

### 8.7 Paket bauen

```bash
uv build
```

Das erzeugt Source-Archiv und Wheel unter `dist/`. Die Paketstruktur umfasst `atelier_api` einschließlich `customers`, `health` und CLI. Migrationen werden für die Entwicklung aus dem Repository ausgeführt.

### 8.8 Häufige Probleme

| Symptom | Prüfung / Lösung |
| --- | --- |
| `database_url` fehlt oder URL kann nicht gelesen werden | `.env` im Projektverzeichnis erstellen, `DATABASE_URL` ausfüllen und exportierte Werte prüfen. |
| Verbindung abgelehnt oder `/health/ready` liefert 503 | PostgreSQL starten, Host/Port und Zugangsdaten prüfen; bei Docker auf erfolgreiche Readiness warten. |
| Kundentabelle fehlt (`relation "customer" does not exist`) | `make db-migrate` mit derselben `DATABASE_URL` wie beim Server ausführen. |
| Port 8000 ist belegt | Anderen Port wählen: `uv run atelier-api --port 8001`. |
| `pg_config` fehlt beim Installieren | PostgreSQL-Entwicklungsdateien installieren und `pg_config` im `PATH` verfügbar machen. |
| PostgreSQL-Readiness-Test schlägt fehl | Testdatenbank starten und `TEST_DATABASE_URL` wie oben setzen. |

Eine fehlende Datenbankverbindung verhindert nicht zwingend den Serverstart. Liveness prüft nur die Anwendung; Readiness führt eine Datenbankabfrage aus. Ein erfolgreicher Readiness-Check bestätigt nicht, dass alle Migrationen angewendet sind.

Bei Verbindungsfehlern oder Pool-Timeouts während API-Datenbankzugriffen wird HTTP 503 mit `Database unavailable` zurückgegeben. Die Readiness-Abfrage meldet HTTP 503 mit `Service unavailable`. Antworten enthalten keine internen Datenbankfehler oder Zugangsdaten. Die Anwendung prüft Pool-Verbindungen vor Wiederverwendung (`pool_pre_ping`).

## 9. Datenschutz, Sicherheit und Betrieb

**Vor Produktivstart zwingend:**

- Geschützte Anmeldung, rollenbasierte Berechtigungen, HTTPS und sichere Secrets.
- Datenminimierung, klare Zugriffsregeln, Lösch-/Aufbewahrungskonzept und DSGVO-Prüfung.
- Geeignete Hosting- und Auftragsverarbeitungsvereinbarungen, soweit erforderlich.
- Automatische, geschützte Backups und **getestete Wiederherstellung**.
- Protokollierung sicherheitsrelevanter Änderungen ohne unnötige Offenlegung personenbezogener Daten.
- Datei-Uploads mit Größen-/Typbeschränkung und geschützter Ablage.
- Signatur-/Vertragsprozess fachlich und rechtlich prüfen.
- Rechnungs-/Steuerprozess vor Livebetrieb mit Steuerberatung abstimmen.
- Pilot zunächst mit Testdaten; reale Excel-Daten nur mit Erlaubnis und angemessenen Schutzmaßnahmen importieren.

## 10. Noch mit Herrn Lampe zu klären

1. Welche Felder und Klauseln enthalten seine **Mietverträge** und **Übergabe-/Rückgabeprotokolle**?
2. Welche Gegenstände werden gemeinsam vermietet (Instrument, Bogen, Kasten, Zubehör)?
3. Welche Zahlungsarten, Mietintervalle, Kautionen, Kündigungs- und Mietkaufregeln verwendet er?
4. Welche Excel-Dateien und Papierformulare existieren, und wie groß sind die Datenbestände?
5. Wie läuft eine typische Reparaturannahme tatsächlich ab; welche Angaben sind unverzichtbar?
6. Arbeitet er allein? Welche Geräte nutzt er (PC, Tablet, Drucker)?
7. Welche Dokumente müssen wie lange aufbewahrt werden; welche Buchhaltungssoftware ist im Einsatz?
8. Welche drei Verwaltungstätigkeiten kosten aktuell am meisten Zeit?

**Produktentscheidung:** Zuerst einen vollständigen Ablauf mit Herrn Lampe testen, statt möglichst viele Einzelfunktionen zu bauen.

## 11. Erfolgskriterien des Piloten

- Ein neuer Reparaturauftrag lässt sich ohne Medienbruch digital anlegen.
- Ein bekanntes Instrument samt Historie ist schnell auffindbar.
- Mietvertrag und Übergabeprotokoll können erstellt, nachvollziehbar unterschrieben und wiedergefunden werden.
- Offene und bezahlte Forderungen sind eindeutig unterscheidbar; Zahlungseingänge werden nicht geraten.
- Daten lassen sich sichern, wiederherstellen und exportieren.
- Die tatsächliche Zeitersparnis wird gemeinsam mit Herrn Lampe an realen Abläufen gemessen (z. B. Bearbeitungszeit vor/nach Einführung).

## 12. Quellen und fachliche Orientierung

- [Deutsches Musikinformationszentrum – Meister Lampe Geigenbau](https://miz.org/de/institutionen/lampe-meister-geigenbau-i31300)
- [Violondio – Geigenbau-Werkstattsoftware](https://www.violondio.com/de/)
- [Stripe – Rechnungsstellung](https://stripe.com/de/invoicing)
- [BGB § 126a – Elektronische Form](https://www.gesetze-im-internet.de/bgb/__126a.html)
- [Bundesfinanzministerium – Informationen zur E-Rechnung](https://www.bundesfinanzministerium.de/)

Die Produktideen aus anderen Lösungen dienen als **Orientierung**. Fremde Texte, Designs, Quellcodes und Datenbestände werden nicht ungeprüft übernommen.

---

**Lizenz:** MIT (laut bestehendem Projekt).  
**Stand dieser README:** 29. Oktober 2026.

**Hinweis:** Fachliche Anforderungen sind ein Arbeitsstand und müssen im Pilot mit Herrn Lampe validiert werden.

### QR-Codes für Instrumente

Mitarbeiter und Administratoren können unter
`GET /api/v1/instruments/{id}/qr-code.svg` einen druckbaren SVG-QR-Code laden.
`PUBLIC_QR_BASE_URL` legt die dauerhafte Basis-URL fest (in Produktion HTTPS).
Ohne Konfiguration werden keine Codes erzeugt. Die Links verwenden zufällige,
unveränderliche Kennungen und bleiben durch Anmeldung und Rollenprüfung geschützt.
Migration, Druck und die aktuelle Weiterleitung zur Datensatz-API sind in
[Instrument QR codes](docs/instrument-qr-codes.md) beschrieben.

### Instrumentenfotos

Private Instrumentenfotos werden in Cloudflare R2 gespeichert; PostgreSQL enthält
nur Metadaten. Mitarbeiter und Administratoren können JPEG-, PNG- und WebP-Fotos
hochladen, anzeigen und herunterladen. Löschanfragen sind Administratoren
vorbehalten und bewahren die Dateien bis zur Klärung der Aufbewahrungsregeln.
Einrichtung, Upload-Limits, API, Bereinigung und Betrieb sind in
[Instrument photo management](docs/instrument-photos.md) beschrieben.

Fotos können innerhalb der konfigurierten Wiederherstellungsfrist durch
Administratoren wiederhergestellt und durch Aufbewahrungssperren geschützt werden.
Der separate Befehl `atelier-photos-purge --dry-run` zeigt Löschkandidaten an.
Dauerhafte Löschung ist standardmäßig deaktiviert und erfordert zusätzlich eine
explizite Freigabe je Foto. Betrieb und Render-Cron-Konfiguration:
[Photo retention](docs/photo-retention.md).
