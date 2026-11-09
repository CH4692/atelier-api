# Realistische Demo-Daten: Small

Der neue Befehl `atelier-demo` erzeugt die rein fiktive Berliner **Werkstatt Klanggarten**. Er verändert keine Tabellen, Migrationen, Endpunkte, Geschäftsregeln oder Frontend-Dateien. Es werden nur bereits vorhandene Modelle und Beziehungen verwendet.

## Bestand und tatsächliche Grenzen

Das Kernprofil enthält:

- 50 Kunden: Privatmusiker, berufliche Nutzung, Musikstudium, Unterricht, Familien und drei Institutionen. Die Nutzungskontexte stehen ausschließlich in vorhandenen Instrumentnotizen; es gibt kein Kundenkategorie-Feld. Vier Kunden sind archiviert, zehn haben kein Instrument, mehrere haben zwei Instrumente. E-Mail und Telefon sind teilweise leer.
- 100 Instrumente: 50 Geigen, 15 Bratschen, 15 Celli, fünf Kontrabässe und 15 Bögen. 70 sind kundeneigen, 25 Werkstattbestand und fünf ohne Zuordnung. Vier sind archiviert. Kategorien, positive Maße, Bogenattribute und Eigentümerzuordnung entsprechen den bestehenden Schemas. QR-UUIDs werden unverändert vom vorhandenen `uuid4`-Mechanismus erzeugt.
- 150 Aufträge: 85 abgeschlossen, zehn storniert, 15 angenommen, zehn warten auf Freigabe, zwölf sind in Arbeit, acht warten auf Material und zehn sind abholbereit. Fünf historische Aufträge sind archiviert. Es gibt wiederkehrende Instrumente/Kunden, bis zu vier Jahre Geschichte, langfristige Restaurierungen und verschiedene Fristen: überfällig, heute, binnen sieben Tagen und später. Aktive Aufträge verweisen auf aktive Kunden und Instrumente.
- 30 echte UTF-8-Textdokumente als Arbeits-/Zwischenberichte mit korrekten Byte-Längen und SHA-256-Prüfsummen. Es werden keine vermeintlichen PDF-Dateien mit ungültigem Inhalt erzeugt.
- Fünf interne Benutzer: ein Administrator, drei aktive Mitarbeiter und ein inaktiver Mitarbeiter. Dazu kommt ein ausdrücklich verknüpftes Kundenkonto für die vorhandenen Portal-/Negativtests, insgesamt also sechs Konten.
- Zwölf vorhandene Reparaturvorlagen, 210 Kostenpositionen und 25 Kostenvoranschläge mit den vorhandenen Dokumentstatus. Beträge und Mengen verwenden `Decimal`. Kostenvoranschläge und Freigaben werden über die bestehenden Services erstellt; sie sind keine Rechnungen und keine elektronischen Signaturen.
- Optional 50 tatsächlich hochgeladene, sichtbar als **fiktive Demo-Illustrationen** beschriftete PNG-Dateien: zwei Ansichten an jeweils 25 Instrumenten. Es sind schematische Originalillustrationen, keine Aufnahmen echter Instrumente. Metadaten ohne vorhandene Binärdaten werden nicht als fertige Fotos angelegt.

Nicht vorhanden und daher **nicht erfunden**: Mietverträge, Rechnungen, Zahlungen, Kunden-Registrierungszeitstempel und eigene Dashboard-Aggregationsendpunkte. Der JSON-Bericht nennt diese Lücken und meldet die nicht vorhandenen Mengen als null Datensätze (`0`). Werkstattbestand kann mögliche Schülervermietung beschreiben, erzeugt aber keinen Mietvertrag. Dashboard-Vorführfälle nutzen vorhandene Auftragsfilter und deren `X-Total-Count`.

Kundennamen und Werkstattangaben sind fiktiv, E-Mail-Adressen verwenden `example.com`. Die Telefonnummern stammen ausschließlich aus dem Berliner Bereich `030 23125 000–999`, den die [Bundesnetzagentur für Medienproduktionen bereitstellt](https://bundesnetzagentur.de/DE/Fachthemen/Telekommunikation/Nummerierung/DramaNumbers/artikel.html). Keine Produktionsdaten, privaten Rufnummern oder Exporte werden verwendet.

## Inventar der bestehenden Architektur

Die Implementierung wurde an SQLModel-Modellen, Pydantic-Schemas und den vorhandenen Alembic-Migrationen ausgerichtet:

- `customer` → `instrument.customer_id`: optionale aktuelle Eigentümerbeziehung; vorhandene Archivierung bleibt unabhängig davon.
- `instrument` → `repair_order`: Reparaturhistorie mit unveränderlichen Kundenreferenzen, Annahme-, Arbeits-, Status- und Fälligkeitsdaten; Löschen referenzierter Instrumente ist eingeschränkt.
- `repair_order` → `repair_document`, `repair_item`, `repair_estimate` → `estimate_item`: echte Dokumentbytes in PostgreSQL, exakte Kosten und unabhängige Kostenvoranschlagsrevisionen.
- `repair_template`: wiederverwendbare Vorgaben; Änderungen überschreiben keine vorhandenen Auftragssnapshots.
- `instrument_photo`: private R2-Objekte mit Namespace, Upload-Intents und bestehendem Wiederherstellungs-/Aufbewahrungsmodell.
- `app_user`, `user_provisioning_state`: einmaliger Administrator-Bootstrap, Rollen, Aktivierung, Kundenverknüpfung und Argon2id-Passwörter. Die Seed-Konten werden ausschließlich über `users/service.py` provisioniert.
- `instrument_ownership_event` und `audit_event`: Eigentums-Trigger und zulässige Audit-Ereignisse bleiben aktiv. Audit-Zeiten beschreiben den tatsächlichen Import, fachliche Reparaturdaten die fiktive Historie. Es werden keine vergangenen Benutzeridentitäten oder alten Login-Sitzungen gefälscht.
- `user_session` und `login_rate_limit`: werden nicht mit gefälschten Authentifizierungsdaten gefüllt. Anmeldung, RBAC, CSRF und das vorhandene Portal-Featureflag bleiben unverändert.

Der Seeder validiert Eingabedaten mit bestehenden Schemas. Historische Reparatursnapshots durchlaufen `validate_transition` für jeden Zustandsschritt, bevor die konsistenten Enddaten gespeichert werden. Werkstattdaten werden nicht über neu erfundene Endpunkte importiert.

## Installation und Vorschau

```bash
uv sync --locked --dev
uv run atelier-demo --dry-run --as-of 2026-11-09
uv run atelier-demo --dry-run --with-photos --as-of 2026-11-09
```

`--profile small` ist der Standard und das einzige implementierte Profil. Die Vorschau validiert alle Planwerte, öffnet weder Datenbank- noch Speicherverbindungen und gibt `dry_run: true` aus. Fotomengen in der Vorschau sind geplante Mengen.

## Befüllen einer eigenen lokalen Demo-Datenbank

Ausschließlich eine **neue, entbehrliche PostgreSQL-Datenbank** verwenden und die Anwendung während des ersten Imports nicht parallel beschreiben lassen. Der Seeder erstellt und migriert keine Datenbank automatisch. Beispiel auf einem eigenen lokalen PostgreSQL-Server:

```bash
createdb atelier_demo
export ENVIRONMENT=development
export ARTELIER_DEMO_DATABASE_URL='postgresql+psycopg://localhost/atelier_demo'
DATABASE_URL="$ARTELIER_DEMO_DATABASE_URL" uv run alembic upgrade head
uv run atelier-demo --confirm-demo-data --as-of 2026-11-09
```

Das Passwort wird verdeckt zweimal abgefragt und durch die vorhandene Passwort-Policy geprüft. Für automatisierte Aufrufe kann `ARTELIER_DEMO_PASSWORD` als Secret-Umgebungsvariable gesetzt werden; es gibt absichtlich keinen Passwort-CLI-Parameter und keine fest eingebauten Zugangsdaten. Passwort, Hash und Verbindungs-URL erscheinen nicht im Seed-Bericht.

Die Konten verwenden das bei der Erstbefüllung gewählte Passwort:

- `meister.demo@example.com`: aktiver Administrator.
- `geigenbau.demo@example.com`, `restaurierung.demo@example.com`, `service.demo@example.com`: aktive Mitarbeiter.
- `pausiert.demo@example.com`: inaktiver Mitarbeiter, Anmeldung wird abgelehnt.
- `kunde.demo@example.com`: Kundenrolle, explizit dem ersten Demo-Kunden zugeordnet. Die vorhandene Anmeldung erlaubt Kunden nur bei aktivierter `CUSTOMER_PORTAL_AUTH_ENABLED`-Konfiguration; Workshop-Rechte entstehen dadurch nicht.

`DATABASE_URL` allein wird **niemals** als Seed-Ziel verwendet. Ohne `ARTELIER_DEMO_DATABASE_URL` und `--confirm-demo-data` gibt es keinen Schreibzugriff. Produktionsmodus, SQLite und PostgreSQL-Datenbanken ohne Suffix `_demo` oder `_test` werden zurückgewiesen. Zusätzlich wird die tatsächliche Verbindungs-URL geprüft. Vorhandene Geschäftsdaten oder ein bereits verwendeter Administrator-Bootstrap ohne Seed-Marker verhindern den Import. Es gibt keinen automatischen Reset, kein Löschen und keine überschreibende Wiederbefüllung.

## Datum, Determinismus, Transaktion und Wiederholung

`--as-of` verankert die fachlichen Daten, einschließlich heutiger und überfälliger Fristen. Ohne Angabe gilt das aktuelle Datum in `Europe/Berlin`. Referenzdaten vor 2000 werden abgelehnt. Bei gleichem Referenzdatum bleiben Inhalte, Verteilungen, Beziehungen, Auswahlreihenfolge und Illustrationen identisch. Herstellungsjahre liegen vor der ältesten Reparatur.

Datenbank-IDs, zufällige öffentliche QR-UUIDs, Argon2-Salts und operative Audit-/Kostenvoranschlags-Zeitstempel bleiben bewusst bei ihren vorhandenen Mechanismen. Beziehungen verwenden die tatsächlich gespeicherten IDs, keine Annahme über Sequenzstarts. Fachliche Seed-Daten sind deterministisch; die gesamte Datenbank ist deshalb kein byteidentisches Dump-Artefakt.

Die Datenbankphase läuft in einer äußeren Transaktion. Bereits vorhandene Services dürfen intern committen; diese Commits lösen nur Savepoints und können den äußeren Seed nicht vorzeitig veröffentlichen. Ein Fehler rollt auch Benutzer und den Bootstrap-Latch zurück. Ein PostgreSQL-Advisory-Lock serialisiert Seed-Läufe.

Nach vollständiger Befüllung steht ein versions- und datumsbezogener Marker in der vorhandenen Notiz des Instruments `ART-DEMO-S-0001`. Ein erneuter Lauf erkennt ihn, meldet `reused: true` und liest aktuelle Mengen. Er setzt weder Passwörter zurück noch überschreibt er manuelle Änderungen. Ein ausdrücklich anderes Referenzdatum wird abgelehnt; ohne `--as-of` bleibt das ursprüngliche Datum erhalten. Der Marker darf nicht entfernt oder umgedeutet werden. Für eine neue Ausgangslage eine neue entbehrliche Demo-Datenbank bereitstellen. Fehlende oder manuell gelöschte Geschäftsdaten werden nicht automatisch rekonstruiert.

## Optionale Fotos über den vorhandenen Speicher

```bash
uv run atelier-demo --confirm-demo-data --with-photos --as-of 2026-11-09
```

Dafür müssen die vorhandenen `R2_*`-Einstellungen auf einen **privaten, dedizierten Demo-/Test-Bucket** zeigen; sein Name muss auf `-demo` oder `-test` enden. Die Datenbank-Schutzprüfungen gelten zusätzlich. Es wird weder ein neuer Storage-Provider implementiert noch ein produktiver Bucket automatisch benutzt. Ohne `--with-photos` meldet der Bericht den ausgelassenen Schritt ausdrücklich.

Fotos werden erst **nach erfolgreichem Commit der Grunddaten** hochgeladen. Dafür werden die bestehenden Bildprüfung, Metadatenbereinigung, zufälligen Storage-Schlüssel, Upload-Intents, bedingten Writes, Audit-Ereignisse und Kompensationsmechanismen verwendet. Ein Speicherfehler lässt die Grunddaten bestehen; bereits fertige Fotos bleiben gültig. Wiederholung mit demselben Ziel und Namespace lädt nur fehlende Illustrationen nach. Eigene Pending-Intents werden vor einem erneuten Upload über den vorhandenen Cleanup-Service bereinigt. Fehlgeschlagene Bereinigung, fehlende fertige Binärdaten, ein anderer Namespace oder gelöschte/aufbewahrte Belege führen zu einem sichtbaren Fehler statt zu Duplikaten oder automatischem Wiederherstellen von Beweisdaten.

Die Datenbank und R2 bilden keine gemeinsame Transaktion. Genau deshalb werden diese Phasen getrennt und der vorhandene Wiederaufnahmeprozess genutzt. Ein echtes R2-Konto wird in automatisierten Tests nicht verwendet; diese injizieren den vorhandenen privaten `FakeStorage`.

## Prüfung und manuelle Vorführung

Gezielte Tests:

```bash
uv run pytest tests/demo -q
uv run pytest --require-postgres tests/integration/test_demo_seed.py -q
```

Die PostgreSQL-Tests verwenden den bestehenden isolierten, migrierten Test-Schema-Mechanismus und ausschließlich `TEST_DATABASE_URL` mit `_test`-Suffix. Sie prüfen Mengen, FK-Beziehungen bei nicht bei eins beginnenden IDs, Zeitkonsistenz, eindeutige QR-UUIDs, Dokument-Hashes, echte Passwortprüfung/Rollen, Rollback nach internen Service-Commits, Wiederholung ohne Passwortwechsel, lesbare APIs sowie Fotoausfall und Wiederaufnahme ohne Duplikate. Vollständige Qualitätsbefehle stehen in `docs/testing.md` und `AGENTS.md`; die bestehenden CI-Jobs entdecken die neuen Unit-/Integrationstests automatisch. Die Wheel-Prüfung lädt den installierten `atelier-demo`-Einstieg auch außerhalb des Repositories und führt einen verbindungslosen Dry-Run aus.

Für manuelle Abnahme: als Mitarbeiter anmelden, Kunden mit und ohne Instrumente öffnen, Archivfilter aktivieren, Kennnummer `ART-DEMO-S-` suchen, Seitenwechsel testen, verschiedene Reparaturstatus und Fristen vergleichen und abholbereite Aufträge öffnen. Dokument- und Foto-APIs sind Backend-Funktionalität; die vorhandene Angular-Oberfläche bietet noch nicht für alle diese Fähigkeiten eigene Arbeitsabläufe. Der Seeder ändert daran nichts und ersetzt nicht die isolierten, jeweils frisch erzeugten Datensätze der vorhandenen Browser-E2E-Tests.

## Lokal verifiziert am 09.11.2026

- Vollständige Nicht-External-Suite mit zwei isolierten PostgreSQL-Workern: **1.416 Tests bestanden**, keine übersprungenen Tests.
- Ruff, Formatprüfung und mypy erfolgreich.
- Wheel und Quelldistribution erfolgreich gebaut; Wheel in einer frischen Umgebung außerhalb des Repositorys installiert, alle bestehenden Paketprüfungen und der Demo-Dry-Run erfolgreich.
- Zusätzlicher echter CLI-Smoke-Test auf einer vollständig neu angelegten, danach entfernten PostgreSQL-Datenbank: Erstimport, Wiederholung ohne Passwort und Ablehnung eines geänderten Stichtags erfolgreich.
- Keine bestehende Entwicklungs-/Produktionsdatenbank und kein echter R2-Bucket wurden für diese Prüfung verwendet. Der Frontend-Checkout blieb unverändert. Ein Remote-CI-Lauf ist für diese noch nicht gepushten Änderungen nicht behauptet.
