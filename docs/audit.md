# Audit-Protokoll

## Zweck und Umfang

Das interne Audit-Protokoll dient der Nachvollziehbarkeit wichtiger Änderungen
und sicherheitsrelevanter Vorgänge. Es ist von Debugging- und HTTP-Logs getrennt.
Es enthält Ereignis-ID, Aktion, Ressourcentyp und gegebenenfalls Ressourcen-ID,
Akteur-ID, einen UTC-Zeitpunkt und Erfolg/Misserfolg. Es kopiert weder Namen,
E-Mail-Adressen, IP-Adressen noch fachliche Freitexte oder Request-Bodies.
Passwörter, Passwort-Hashes, Session-Tokens und Token-Hashes sind ausgeschlossen.
Administrative Zusatzinformationen sind auf alte/neue Rollen, alte/neue
Kundenzuordnungs-IDs und Bereinigungsanzahlen begrenzt; die zentrale Schreibfunktion
akzeptiert dafür nur ein streng definiertes Schema.

Erfasst werden Kunden- und Instrumentanlage, Änderungen und Löschung;
Kundenarchivierung (`customer.archived`) und Wiederherstellung (`customer.restored`)
werden mit der Statusänderung atomar gespeichert, ohne Zuordnungen zu ändern.
Ebenfalls erfasst werden Bootstrap,
Benutzeranlage, Aktivierung/Deaktivierung (auch von Kundenkonten), Rollen- und
Kundenzuordnungsänderungen, Benutzerlöschung und die damit verbundenen
Session-Sperrungen. Auch die automatische Aufhebung einer Kontenzuordnung beim
Löschen eines Kunden wird in derselben Transaktion erfasst; das gilt auch für
die automatische Aufhebung der Instrumentzuordnung. Session-Login (einschließlich Fehlschlägen und Drosselung),
Logout, Rotation/Sperrung, abgewiesene vorhandene Cookies und Session-Bereinigung
werden ebenfalls erfasst. Das gilt auch für lokale CLI-Anmeldungen zur
Benutzerverwaltung. Fehlgeschlagene Logins enthalten bewusst keine vermutete
Benutzer-ID und keine eingegebene E-Mail-Adresse. Fehlende Cookies erzeugen bei
öffentlichen Zugriffen kein zusätzliches Ereignis. Ungültige vorhandene Cookies
werden ohne ihren Inhalt protokolliert.

Kundenportal-Anmeldungen und abgewiesene Sessions benutzen dieselben Ereignisse;
abgewiesene Werkstatt- und Audit-Zugriffe angemeldeter Konten werden ebenfalls
erfasst. Es gibt keinen kundenseitigen Zugriff auf das interne Protokoll. Erfolgreiche
Audit-Abfragen erzeugen ein `audit.read`-Ereignis mit der Akteur-ID, ohne Filterwerte
oder Antwortinhalte zu kopieren. Das Ereignis wird vor der Antwort committet und
erscheint frühestens in einer nachfolgenden Abfrage. Auch leere Ergebnisse werden
erfasst. API-Zeitstempel werden unabhängig von der Datenbank-Zeitzone in UTC
ausgegeben. Validierungsfehler,
404-Antworten und beliebige HTTP-Anfragen werden nicht pauschal protokolliert.

Die Reparaturhistorie erfasst `repair_order.created`, `repair_order.archived`,
`repair_order.restored` und `repair_document.created` atomar mit der jeweiligen
Änderung. Arbeitsbeschreibungen, Dateinamen und Dokumentinhalte werden nicht
kopiert. Die fachliche Reparatur-/Dokumentablage ist von der Audit-Aufbewahrung
unabhängig. Mietverträge, Vertragsabschluss und Rechnungen existieren noch nicht. Ihre fachlichen Aktionen müssen bei Einführung der jeweiligen Features
explizite Audit-Aktionen und Tests erhalten; dieses Modul erzeugt dafür keine
fiktiven Vorgänge. Direkte SQL-Änderungen außerhalb der Anwendung werden nicht
als fachliche Ereignisse erfasst.

## Zugriff und Transaktionen

`GET /api/v1/audit-events` verlangt eine gültige Session und die aktuelle Rolle
`admin`. Mitarbeiter und Kundenkonten erhalten keinen Zugriff. Es gibt keine
Anwendungs-API zum Anlegen, Ändern oder Löschen von Ereignissen. Filter:
`actor_id`, `action`, `resource_type`, `resource_id`, `since`, `until` (einschließlich
Grenzen, mit Zeitzone). Maximal 200 Einträge werden absteigend nach Ereignis-ID
geliefert; `before_id` setzt die nächste Seite fort. Es werden keine persönlichen
Konten- oder Kundendaten per Join hinzugefügt.

Fachliche Änderungen und ihre Audit-Ereignisse werden in derselben Transaktion
committet. Ein Schreibfehler im Audit-Protokoll verhindert auch den fachlichen
Commit. Session-Rotation und ihr Audit-Ereignis sind ebenfalls atomar.
Fehlgeschlagene Anmeldungen und Drosselungen werden vor der Fehlerantwort bewusst
committet, damit der abschließende Request-Rollback sie nicht entfernt.
Login-Zähler haben weiterhin ihre eigenen Commits zur zuverlässigen Drosselung.

Akteur- und Ressourcen-IDs sind historische Referenzen ohne kaskadierende
Fremdschlüssel. Deaktivierung und Benutzerlöschung löschen daher keine vorhandenen
Ereignisse. IDs dürfen operativ nicht durch Rücksetzen von Sequenzen erneut
vergeben werden. Bootstrap und vertrauenswürdige lokale Bereinigungsbefehle haben
keinen angemeldeten Anwendungsbenutzer; dort ist `actor_id` null.

## Aufbewahrung und Datenschutz

Der technische Standard ist **180 Tage**, konfigurierbar mit
`AUDIT_RETENTION_DAYS` (mindestens 1 Tag). Der Betreiber muss die für seinen Zweck
notwendige Frist und Rechtsgrundlage festlegen, dokumentieren und die Einstellung
entsprechend anpassen. IDs und Rollenhistorien sind trotz Datenminimierung weiterhin
personenbeziehbar. Zugriffe auf Datenbank und Backups sind entsprechend zu beschränken.
Dieses technische Konzept ersetzt keine Prüfung der betrieblichen Datenschutzpflichten.

Der vertrauenswürdige Datenbankbetreiber plant täglich:

```bash
uv run atelier-audit-cleanup
```

Der Befehl entfernt ausschließlich Ereignisse vor dem UTC-Stichtag und schreibt
in derselben Transaktion ein neues `audit.retention`-Ereignis mit der Anzahl.
Es gibt keine API zum Verkürzen der Frist oder selektiven Entfernen einzelner
Ereignisse. Ohne Ausführung dieses Betreiberbefehls erfolgt keine automatische
Löschung. Backup-Aufbewahrung und Wiederherstellung müssen dieselbe Löschpolitik
berücksichtigen; nach Wiederherstellung ist die Bereinigung erneut auszuführen.
Ein rechtlich erforderlicher Aufbewahrungsstopp muss vor der Bereinigung durch den
Betreiber geregelt werden.

## Integritätsgrenzen

Das Protokoll ist **nicht manipulationssicher**. Der normale Anwendungszugriff ist
nur lesend, aber die Datenbank-Zugangsdaten der Anwendung besitzen aktuell auch
Schreibrechte. Ein kompromittierter Prozess, Datenbankbetreiber oder Superuser
kann Ereignisse über SQL verändern, entfernen oder erfinden; es gibt weder externe
Versiegelung noch eine unabhängige Archivierung oder kryptographische Beweiskette.
Die Retentions-CLI setzt ebenfalls vertrauenswürdigen lokalen Datenbankzugriff
voraus. Produktionsbetrieb sollte Laufzeit-, Migrations- und Bereinigungsrollen
trennen, SQL-Zugriff beschränken und insbesondere UPDATE/DELETE nur berechtigten
Betreiberrollen ermöglichen. Solche datenbankseitigen Berechtigungen müssen vom
Deployment passend zu den verwendeten Rollen eingerichtet werden.

Instrument photographs record `instrument_photo.uploaded` and
`instrument_photo.deletion_requested`, with the acting user and photo ID plus
`instrument_id` in allowed details. Success events share the transaction with
ready metadata or soft deletion. Filenames, object keys, binaries, R2 credentials
and URLs are excluded. The retention feature also records restoration, hold creation/release, explicit
purge approval, purge start, failure and completion. Scheduled events have a UUID
`execution_id` and no acting user. Purge completion is atomic with photo-row
removal; its audit reference remains. Hold reasons and filenames are not included.
Purge start occurs once, while failed retry attempts have their own job IDs. See
[instrument photo management](instrument-photos.md) for upload reconciliation.
