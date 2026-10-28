# Modulstruktur und Architektur

Atelier API ist ein modularer Monolith: Eine FastAPI-Anwendung, ein gemeinsam gebautes Python-Paket und eine PostgreSQL-Datenbank. Fachliche Features liegen in eigenen Unterpaketen von `atelier_api`. Sie werden gemeinsam ausgeliefert und über `main.py` verbunden.

## Verbindliche Struktur für Features

```text
src/atelier_api/
├── __init__.py
├── main.py                   # App erstellen und Router registrieren
├── cli.py                    # Prozessstart und CLI-Argumente
├── settings.py               # Zentrale Konfiguration aus Umgebung / .env
├── database.py               # Engine, get_session und SessionDep
├── customers/
│   ├── __init__.py
│   ├── router.py             # HTTP-Endpunkte
│   ├── models.py             # SQLModel-Tabellen
│   └── schemas.py            # API-Eingaben und -Ausgaben
├── instruments/
│   ├── __init__.py
│   ├── router.py             # Instrumente per POST registrieren
│   ├── models.py             # Instrumenttabelle und optionale Kundenbeziehung
│   └── schemas.py            # Instrumenttyp und validierte Ein-/Ausgaben
└── health/
    ├── __init__.py
    └── router.py             # Technische Zustandsprüfungen
```

Für neue Features gilt das Muster von `customers`. Jedes Feature erhält ein `__init__.py` und einen `router.py`, wenn es HTTP-Endpunkte anbietet. `models.py` wird bei eigenen Tabellen angelegt, `schemas.py` bei eigenen Ein- oder Ausgabemodellen. Weitere Dateien kommen nach Bedarf hinzu:

| Datei | Verantwortung | Wann benötigt? |
| --- | --- | --- |
| `router.py` | Request-Parameter, Dependency-Injection, HTTP-Statuscodes, Antwortmodelle | Bei HTTP-Endpunkten |
| `schemas.py` | Struktur und Validierung von API-Eingaben und -Ausgaben | Bei fachlichen Payloads |
| `models.py` | Tabellen, Spalten, Constraints und Datenbankbeziehungen | Bei eigener Persistenz |
| `service.py` | Geschäftsregeln und fachliche Anwendungsfälle | Bei komplexeren oder wiederverwendeten Abläufen |
| `dependencies.py` | Feature-spezifische FastAPI-Dependencies | Bei wiederverwendeter Vorbereitung von Requests |
| `exceptions.py` | Fachliche Fehler ohne HTTP-Kopplung | Wenn Services eigene Fehler melden |

Technische Module wie `health` benötigen nicht automatisch Modelle, Schemas oder Services. Leere Platzhalterdateien sind nicht erforderlich.

## Verantwortlichkeiten und Geschäftslogik

Der Router ist der HTTP-Einstiegspunkt. Er validiert Parameter über Schemas, erhält Dependencies und übersetzt Ergebnisse oder fachliche Fehler in HTTP-Antworten. Datenbanktabellen gehören in `models.py`, API-Verträge in `schemas.py`. Tabellenmodelle werden nicht direkt als öffentliche Antwortmodelle verwendet.

Aktuell bleiben die einfachen Kundenoperationen im Router. `CustomerCreate` und `CustomerRead` sind API-Schemas; `Customer` ist das Tabellenmodell und erbt die gemeinsamen Felder von `CustomerBase`. Diese bestehende Wiederverwendung ist zulässig. Schemas importieren keine Tabellenmodelle und verwenden keine Datenbank-Session.

Sobald beispielsweise eine Reparaturannahme mehrere Geschäftsregeln oder Schreiboperationen umfasst, kommt der Ablauf in das `service.py` des zuständigen Features. Dasselbe gilt für Logik, die von mehreren Endpunkten oder einem späteren Hintergrundprozess verwendet wird.

Für Services gelten folgende Regeln:

- Sie erhalten benötigte Werte und eine Session ausdrücklich als Argumente. Sie verwenden weder `Depends`, `Request` noch `HTTPException`.
- Fachliche Fehler werden als eigene Exceptions gemeldet; der Router übersetzt sie beispielsweise in 404 oder 409.
- Zusammengehörige Schreiboperationen bilden eine Transaktion. Der aufgerufene Service übernimmt bei einem solchen Anwendungsfall den Commit; Hilfsfunktionen committen nicht unabhängig. Bei den bestehenden einfachen Kundenoperationen liegt der Commit weiterhin im Router.
- Ein Service öffnet keine versteckte eigene Session. So bleiben Transaktionsgrenzen und Tests kontrollierbar.
- Ein synchroner Service bleibt synchron. Neue Router mit synchronen Datenbankoperationen verwenden `def`; eine vollständige Umstellung bestehender `async def`-Router ist ein separates Thema.

Eine zusätzliche Repository-Schicht ist erst bei konkretem Bedarf vorgesehen, beispielsweise wenn dieselben komplexen Abfragen mehrfach benötigt werden.

## Gemeinsame Dependencies

`database.py` ist der gemeinsame Ort für Engine, `get_session` und `SessionDep`. Features verwenden diese Dependency und erzeugen keine eigenen Engines. `settings.py` ist die einzige Quelle für Anwendungskonfiguration; auch Alembic verwendet diese Settings.

Weitere fachübergreifende Request-Dependencies, etwa eine spätere Benutzeranmeldung, gehören bei Einführung nach `atelier_api/dependencies.py`. Feature-spezifische Dependencies liegen unter `<feature>/dependencies.py`. Die zentrale Dependency-Schicht importiert keine Feature-Router.

`main.py` ist der Ort für das Zusammenstellen der Anwendung. Features importieren die globale App nicht; sie exportieren Router, die dort registriert werden. Tests dürfen die App importieren und Dependencies für die Dauer eines Tests überschreiben; anschließend stellen sie die vorherigen Overrides wieder her.

## Namen und Imports

- Feature-Pakete verwenden englische fachliche Namen im Plural und `snake_case`, beispielsweise `customers` oder später `repair_orders`.
- Dateien und Funktionen verwenden `snake_case`, Klassen `PascalCase`. API-Schemas heißen beispielsweise `CustomerCreate` und `CustomerRead`.
- Router heißen `<feature>_router`, beispielsweise `customers_router`, mit dem passenden URL-Präfix `/customers` und Tag `customers`.
- Zwischen Paketen werden absolute Imports ab `atelier_api` verwendet. Innerhalb eines Features sind relative Imports vorgesehen.

```python
# Gemeinsame Dependency und feature-interne Schemas in customers/router.py
from atelier_api.database import SessionDep

from .schemas import CustomerCreate, CustomerRead
```

Neue Features liegen ausschließlich unter `src/atelier_api/`, damit sie im Wheel enthalten sind. Imports wie `from customers.models import Customer` sind nicht vorgesehen. `__init__.py` bleibt frei von App-Start, Datenbankabfragen oder automatischer Router-Registrierung.

Features rufen keine HTTP-Handler anderer Features auf. Eine benötigte fachübergreifende Operation verwendet eine ausdrücklich benannte Service-Funktion des zuständigen Features. Tabellenbeziehungen dürfen Modelle referenzieren; zyklische Laufzeit-Imports sind zu vermeiden. Neue fachliche Abhängigkeiten müssen nachvollziehbar und gerichtet bleiben.

## Bestehende Instrumentbeziehung

`instruments.models.Instrument` referenziert `customers.models.Customer` über einen optionalen Fremdschlüssel. Die Abhängigkeit ist gerichtet: `customers` importiert `instruments` nicht. Das Modell stellt die ORM-Beziehung `Instrument.customer` bereit. Beim Löschen eines Kunden erhält `ON DELETE SET NULL` die Instrumentdaten und hebt nur die Zuordnung auf. Der in `main.py` registrierte Instrument-Router bietet `POST /instruments` an. Er prüft einen optional angegebenen Kunden vor dem Speichern; unbekannte Kunden ergeben HTTP 404, ungültige Eingaben HTTP 422.

## Neues Feature ergänzen

1. Unterpaket in `src/atelier_api/<feature>/` mit den tatsächlich benötigten Dateien anlegen.
2. API-Verträge in `schemas.py` und gegebenenfalls Tabellen in `models.py` definieren.
3. Router mit Präfix und Tags erstellen; gemeinsame Session-Dependency verwenden.
4. Bei fachlicher Komplexität Service und fachliche Exceptions ergänzen.
5. Router in `main.py` importieren und mit `app.include_router(...)` registrieren.
6. Neue Tabellenmodelle in `alembic/env.py` importieren, damit Alembic sie in `SQLModel.metadata` erkennt. Migration erzeugen, prüfen und anwenden; kein `create_all()` beim Serverstart.
7. Tests unter `tests/<feature>/` anlegen. HTTP-Verhalten über den TestClient, Services direkt und Datenbankoperationen über PostgreSQL-Integrationstests prüfen, sobald diese im jeweiligen Branch verfügbar sind.
8. Dokumentation der Endpunkte und der erforderlichen Konfiguration aktualisieren.

## Bestehende Funktionalität prüfen

Aus dem Projektverzeichnis und mit konfigurierter Testdatenbank:

```bash
make db-migrate
make db-check
make test
make lint
make typecheck
uv build
```

Migrationen und Tests ausschließlich gegen die dafür vorgesehene Testdatenbank ausführen; die Einrichtung steht in der [README](../README.md#8-einrichtung-und-lokale-entwicklung). Die CI prüft zusätzlich die Installation des gebauten Wheels außerhalb des Quellcodeverzeichnisses. Bestehende URLs, Statuscodes und Antwortschemas sollen bei reinen Strukturänderungen erhalten bleiben.
