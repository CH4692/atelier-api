# Atelier API – Digitale Werkstattverwaltung für Geigenbau

> **Status:** Früher Prototyp (Version 0.1.0). Die Anwendung ist **nicht produktionsreif**.  
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

Aktuell sind folgende Endpunkte implementiert:

| Methode | Pfad                       | Verhalten                                             |
| ------- | -------------------------- | ----------------------------------------------------- |
| `GET`   | `/`                        | Gibt „Hello World“ zurück                             |
| `GET`   | `/health/live`             | Liveness-Prüfung                                      |
| `GET`   | `/health/ready`            | Prüft die Datenbankverbindung                         |
| `GET`   | `/customers`               | Gibt derzeit alle Kunden ohne Pagination zurück       |
| `GET`   | `/customers/{customer_id}` | Gibt einen Kunden zurück; `404` falls nicht vorhanden |
| `POST`  | `/customers`               | Legt einen Kunden an; `201` bei Erfolg                |

**Aktuelles Kundenmodell:** numerische ID, Vorname, Nachname, E-Mail-Adresse und optionale Telefonnummer. Bearbeiten, Löschen, Suche, Filter und Pagination sind noch nicht implementiert.

**Wichtige offene Befunde der Bestandsaufnahme:**

- **Hoch:** Authentifizierung und Autorisierung fehlen; keine echten Kundendaten in einer öffentlich erreichbaren Instanz verwenden.
- **Mittel:** Synchrone Datenbankaufrufe innerhalb von `async def`-Routen.
- **Mittel:** Fehlende Pagination, Sortierung und stärkere Eingabevalidierung.
- **Mittel:** Kunden-API-Tests verwenden Mocks statt einer echten PostgreSQL-Testdatenbank.
- **Mittel:** Eine Konfiguration für den produktiven Betrieb steht noch aus.

Die Anwendungsmodule einschließlich `customers` und `health` werden gemeinsam als Paket `atelier_api` ausgeliefert. Der CLI-Einstiegspunkt lautet `atelier_api.cli:main`. Die CI prüft Lint, Typen, Tests, Datenbankmigrationen sowie die Installation und Imports des gebauten Wheels in einer separaten Umgebung.

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

Der Datenfluss ist `HTTP/JSON → FastAPI-Router → Datenbank-Session → SQLModel/SQLAlchemy → PostgreSQL`.

```text
src/atelier_api/
├── main.py           # FastAPI-App und Registrierung der Router
├── cli.py            # Startbefehl atelier-api (Uvicorn)
├── settings.py       # Konfiguration aus Umgebung und .env
├── database.py       # Engine und Session pro Anfrage
├── customers/        # Kunden-Router, API-Schemas und Tabellenmodell
└── health/           # Liveness und Datenbank-Readiness
alembic/              # Migrationskonfiguration und versionierte Schemaänderungen
tests/                # API- und Schema-Tests
scripts/              # Prüfung des installierten Wheels
.github/workflows/    # CI-Prüfungen
```

`CustomerCreate` validiert Eingaben, `CustomerRead` beschreibt Antworten und `Customer` bildet die Datenbanktabelle ab. Die Kunden-Router verwenden synchrone SQLModel-Sessions über FastAPI-Dependencies. Alembic erstellt und verändert das Schema; der Server legt Tabellen beim Start nicht automatisch an. Eine Benutzeroberfläche ist noch nicht enthalten.

## 6. Vorgeschlagenes fachliches Datenmodell

Die folgende Skizze ist **kein vorhandenes Datenbankschema**, sondern eine Planung:

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
- [ ] Authentifizierung und Berechtigungen implementieren.
- [ ] PostgreSQL-Integrationstests und reproduzierbare Testdatenbank einrichten.
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

<<<<<<< HEAD
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

In `.env` das zuvor vergebene Passwort eintragen. Das Docker-Beispiel passt ohne weitere Anpassung zur Vorlage:

```dotenv
DATABASE_URL=postgresql+psycopg://atelier:atelier_local@localhost:5432/atelier
```

| Variable | Pflicht | Bedeutung |
| --- | --- | --- |
| `DATABASE_URL` | Ja | SQLAlchemy-Verbindungs-URL; Format `postgresql+psycopg://BENUTZER:PASSWORT@HOST:PORT/DATENBANK`. Kein Standardwert. |

`postgresql+psycopg` wählt den Psycopg-3-Treiber. `localhost:5432` bezeichnet den Datenbankserver; das letzte `atelier` den Datenbanknamen. Sonderzeichen im Benutzer oder Passwort müssen in der URL prozentkodiert werden, beispielsweise `@` als `%40`.

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

Tests gegen die separate Datenbank `atelier_test` ausführen. Das folgende Beispiel verwendet das lokale Docker-Passwort; bei eigener Installation entsprechend anpassen:

```bash
DATABASE_URL=postgresql+psycopg://atelier:atelier_local@localhost:5432/atelier_test make db-migrate
DATABASE_URL=postgresql+psycopg://atelier:atelier_local@localhost:5432/atelier_test make test
make lint
make typecheck
```

Kunden-API-Tests verwenden derzeit gemockte Sessions. Der Readiness-Test benötigt eine echte erreichbare Datenbank. Für künftige Integrationstests die Trennung zwischen Entwicklungs- und Testdatenbank beibehalten.

| Make-Befehl | Direkter Aufruf |
| --- | --- |
| `make test` | `uv run pytest` |
| `make lint` | `uv run ruff check .` |
| `make lint-fix` | `uv run ruff check . --fix` (ändert Dateien) |
| `make typecheck` | `uv run mypy src` |

Die GitHub-Actions-CI startet PostgreSQL 17 für Tests und Migrationsprüfungen und wendet Migrationen vor den Tests an. Ein eigener Job baut und installiert das Wheel in einer frischen Umgebung und prüft die Anwendung außerhalb des Quellcodeverzeichnisses.

### 8.7 Paket bauen

```bash
uv build
```

Das erzeugt Source-Archiv und Wheel unter `dist/`. Die Paketstruktur umfasst `atelier_api` einschließlich `customers`, `health` und CLI. Migrationen werden für die Entwicklung aus dem Repository ausgeführt.
=======
Voraussetzungen: Python 3.14, `uv`, `make` und eine laufende PostgreSQL-Instanz (CI: PostgreSQL 17). Für den möglichen Build von `psycopg2` werden ein C-Compiler und PostgreSQL-Entwicklungsdateien mit `pg_config` im `PATH` benötigt.

```bash
uv python install
uv sync --locked --dev
cp .env.example .env
```

Alle Projektbefehle im Verzeichnis mit `pyproject.toml` ausführen. `.env` lokal bearbeiten; sie wird relativ zum Arbeitsverzeichnis geladen.

### PostgreSQL und Umgebungsvariablen

Als lokaler PostgreSQL-Administrator einen Benutzer und getrennte Entwicklungs- und Testdatenbanken anlegen (Administratorkonto bei Bedarf anpassen):

```bash
createuser -h localhost -U postgres --pwprompt atelier
createdb -h localhost -U postgres --owner=atelier atelier
createdb -h localhost -U postgres --owner=atelier atelier_test
```

`--pwprompt` fragt das neue Passwort ab. In `.env` denselben Wert verwenden:
>>>>>>> 965e7f4 (feat: standardize database configuration)

### 8.8 Häufige Probleme

<<<<<<< HEAD
| Symptom | Prüfung / Lösung |
| --- | --- |
| `database_url` fehlt oder URL kann nicht gelesen werden | `.env` im Projektverzeichnis erstellen, `DATABASE_URL` ausfüllen und exportierte Werte prüfen. |
| Verbindung abgelehnt oder `/health/ready` liefert 503 | PostgreSQL starten, Host/Port und Zugangsdaten prüfen; bei Docker auf erfolgreiche Readiness warten. |
| Kundentabelle fehlt (`relation "customer" does not exist`) | `make db-migrate` mit derselben `DATABASE_URL` wie beim Server ausführen. |
| Port 8000 ist belegt | Anderen Port wählen: `uv run atelier-api --port 8001`. |
| `pg_config` fehlt beim Installieren | PostgreSQL-Entwicklungsdateien installieren und `pg_config` im `PATH` verfügbar machen. |
| Readiness-Test erhält 503 | Testdatenbank starten und die Test-URL ausdrücklich wie oben setzen. |

Eine fehlende Datenbankverbindung verhindert nicht zwingend den Serverstart. Liveness prüft nur die Anwendung; Readiness führt eine Datenbankabfrage aus. Ein erfolgreicher Readiness-Check bestätigt nicht, dass alle Migrationen angewendet sind.
=======
| Variable | Pflicht | Bedeutung |
| --- | --- | --- |
| `DATABASE_URL` | Ja | SQLAlchemy-URL: `postgresql+psycopg://BENUTZER:PASSWORT@HOST:PORT/DATENBANK`. Kein Standardwert. |

Exportierte Umgebungsvariablen überschreiben Werte aus `.env`. Sonderzeichen im Benutzer oder Passwort prozentkodieren, beispielsweise `@` als `%40`. Die Settings prüfen die URL-Syntax und den SQLAlchemy-Dialekt; PostgreSQL benötigt einen Datenbanknamen. Konfigurationsfehler zeigen den eingegebenen Wert nicht an. Die Validierung baut keine Verbindung auf und prüft weder Passwort noch Erreichbarkeit.

`.env` und Varianten wie `.env.test` sind in Git ignoriert; nur `.env.example` wird als Vorlage versioniert. Automatisch geladen wird ausschließlich `.env`. Andere Konfigurationen über die Umgebung bereitstellen. Keine echten Zugangsdaten committen. Falls dies versehentlich geschieht, Zugangsdaten ersetzen: `.gitignore` entfernt sie nicht aus der Historie.

### Migrationen: online und offline

Anwendung sowie beide Alembic-Modi verwenden dieselbe `DATABASE_URL` aus `atelier_api.settings`. Eine zweite URL in `alembic.ini` ist nicht erforderlich.

```bash
# Online: mit der Datenbank verbinden und Migrationen anwenden
make db-migrate

# Aktuellen Stand und Übereinstimmung mit den Modellen prüfen
uv run alembic current
make db-check

# Offline: SQL ohne laufende Datenbank erzeugen, nicht ausführen
uv run alembic upgrade head --sql > migration.sql

# Nach einer Modelländerung eine Migration erzeugen und Datei prüfen
make db-migration message="describe change"

# Letzte Migration zurücknehmen; kann Daten löschen
make db-downgrade
```

Migrationen vor dem Serverstart anwenden; die Anwendung erstellt Tabellen nicht automatisch. Beim Online-Verbindungsfehler beendet Alembic den Befehl mit einem Fehlerstatus und einem verständlichen Hinweis auf `DATABASE_URL` und die Datenbankerreichbarkeit. Zugangsdaten werden dabei nicht ausgegeben.

### Server und Prüfungen

```bash
# Entwicklungsserver mit automatischem Neuladen
make dev

# Alternativ CLI ohne automatisches Neuladen
uv run atelier-api --host 127.0.0.1 --port 8000

# Tests mit separater Datenbank; Passwort lokal ersetzen
DATABASE_URL=postgresql+psycopg://atelier:CHANGE_ME@localhost:5432/atelier_test make db-migrate
DATABASE_URL=postgresql+psycopg://atelier:CHANGE_ME@localhost:5432/atelier_test make test

make lint
make typecheck
uv build
```

API-Dokumentation: http://127.0.0.1:8000/docs. Liveness: `/health/live`. Datenbankbereitschaft: `/health/ready`. Der Readiness-Test benötigt eine erreichbare Datenbank; die Kunden-API-Tests verwenden derzeit gemockte Sessions.

Bei Verbindungsfehlern oder Pool-Timeouts während API-Datenbankzugriffen wird HTTP 503 mit `Database unavailable` zurückgegeben. Die Readiness-Abfrage meldet HTTP 503 mit `Service unavailable`. Antworten enthalten keine internen Datenbankfehler oder Zugangsdaten. Die Anwendung prüft Pool-Verbindungen vor Wiederverwendung (`pool_pre_ping`).

Eine nicht erreichbare Datenbank verhindert nicht zwingend den Serverstart. Bei 503 PostgreSQL, Host, Port und Zugangsdaten prüfen. Ein erfolgreicher Readiness-Check bestätigt nur die Verbindung, nicht den Migrationsstand. Bei fehlender Kundentabelle `make db-migrate` mit derselben URL wie beim Server ausführen.
>>>>>>> 965e7f4 (feat: standardize database configuration)

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
**Stand dieser README:** 28. Oktober 2026.

**Hinweis:** Fachliche Anforderungen sind ein Arbeitsstand und müssen im Pilot mit Herrn Lampe validiert werden.
