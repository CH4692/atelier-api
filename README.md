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

Nach der vorliegenden Codex-Bestandsaufnahme sind **nur** folgende Endpunkte implementiert:

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
- **Hoch:** Das gebaute Wheel enthält offenbar nicht alle Module (`customers`, `health`).
- **Hoch:** Der konfigurierte CLI-Einstiegspunkt `atelier_api:main` verweist auf keine vorhandene Funktion.
- **Mittel:** Synchrone Datenbankaufrufe innerhalb von `async def`-Routen.
- **Mittel:** Fehlende Pagination, Sortierung und stärkere Eingabevalidierung.
- **Mittel:** Kunden-API-Tests verwenden Mocks statt einer echten PostgreSQL-Testdatenbank.
- **Mittel:** Einrichtung, Migrationen und Betrieb sind noch nicht ausreichend dokumentiert.

Zuletzt berichtete Prüfergebnisse: **21 Tests bestanden, 1 Test fehlgeschlagen** (Readiness-Test erhielt ohne erreichbare Datenbank `503`); Ruff, mypy und Build liefen durch. Diese Angaben sind ein **übernommener Prüfstand**, keine neue Ausführung.

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

Aktuell ist der Datenfluss im Backend: `HTTP → FastAPI-Router → Datenbank-Session → SQLModel → PostgreSQL`. Zusätzliche Service-/Repository-Schichten nur einführen, wenn die Fachlogik sie sinnvoll macht.

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

- [ ] Wheel-Paketierung korrigieren und Installation aus gebautem Wheel testen.
- [ ] CLI-Einstiegspunkt reparieren oder entfernen.
- [ ] Lokale Einrichtung, Migrationen und Testausführung dokumentieren.
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

> **Hinweis:** Die folgenden Befehle sind eine allgemeine Orientierung auf Basis des bekannten Stacks. Die tatsächlichen Modulpfade, Umgebungsvariablen und Startbefehle müssen am Repository geprüft werden; die Paketierungsprobleme sind noch offen.

Voraussetzungen: Python ≥ 3.14, `uv`, PostgreSQL.

```bash
# Abhängigkeiten einschließlich Entwicklungswerkzeugen installieren
uv sync --locked --dev

# Tests und Qualitätsprüfungen
uv run pytest
uv run ruff check .
uv run mypy .

# Build
uv build
```

Die Anwendung verwendet laut Bestandsaufnahme `DATABASE_URL` aus der Umgebung bzw. `.env`. Ein **beispielhafter**, lokal anzupassender Wert:

```dotenv
DATABASE_URL=postgresql+psycopg://atelier:CHANGE_ME@localhost:5432/atelier
```

Keine Zugangsdaten committen. Ein korrektes `.env.example` ohne Geheimnisse sowie verifizierte Befehle für Migration und Serverstart sind noch zu ergänzen. Derzeit **nicht** blind den deklarierten `atelier-api`-CLI-Befehl verwenden, da sein Einstiegspunkt laut Bestandsaufnahme defekt ist.

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
**Stand dieser README:** 27. Oktober 2026.  
**Hinweis:** Fachliche Anforderungen sind ein Arbeitsstand und müssen im Pilot mit Herrn Lampe validiert werden.
