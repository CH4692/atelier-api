# Versionierung und Releases

## Entscheidung

| Strategie | Branch-Schutz und CI | Paket, Deployment und Reproduzierbarkeit | Sicherheit und Pflege |
| --- | --- | --- | --- |
| App pusht Versionscommit | Neuer Commit benötigt eigene Checks oder einen wirksamen Bypass | Statische Version leicht lesbar; geprüftes Ausgangsobjekt und Release-Commit unterscheiden sich | Branch-Schreibrecht und Bypass nötig; Teilfehler und Schleifen müssen behandelt werden |
| Tags auf geprüften Commits (gewählt) | Kein Push auf `main`; Tag zeigt exakt auf erfolgreich geprüften Code | Git-basierte Paketversion; Wheel, Source-Archiv, GitHub Release und OpenAPI stimmen überein | Kein Branch-Bypass nötig; zusätzliche Build-Plugins, ansonsten einfacher Ablauf |
| Release-Pull-Request | Versionsänderungen durchlaufen reguläre Reviews und Checks | Statische Version bleibt konsistent; Veröffentlichung erst nach geprüftem Merge | Kein Bypass nötig, aber zweistufige Automatisierung, PR-Rechte und Konfliktbehandlung |

Tag-basierte Releases sind mit Python Semantic Release 10.7.0 offiziell über
`commit: false`, `tag: true`, `push: true` unterstützt. Diese Kombination pusht
nur den Tag, keinen Versionscommit. Ein bloßes Abschalten des Commits bei
statischer `project.version` wäre unvollständig: Neubauten späterer Tags würden
sonst eine veraltete Version melden.

## Eine maßgebliche Version

Releaseversionen stammen aus `vMAJOR.MINOR.PATCH`-Tags. `project.dynamic` enthält
`version`; es gibt keine manuell gepflegte `project.version`. Der gepinnte
Hatchling-Backend mit `hatch-vcs` und `setuptools-scm` setzt die Version in die
Paketmetadaten. Das ersetzt `uv_build`, ohne die Laufzeitabhängigkeiten oder
PostgreSQL-Treiber zu ändern. `uv` bleibt Build-, Lock- und Installationswerkzeug.

Semantic Release berechnet die nächste Version aus den Commit-Nachrichten. Vor
Erstellung des Tags erhält ausschließlich der Release-Build diese berechnete
Version über `SETUPTOOLS_SCM_PRETEND_VERSION="$NEW_VERSION"`. Der Build prüft die
Metadaten von Wheel und Source-Archiv, bevor der Tag veröffentlicht wird. Ein
sauberer Neubau des veröffentlichten Tags benötigt diese Variable nicht.
Source-Archive können auch ohne `.git` zu Wheels gebaut werden. GitHub-Quell-ZIPs
sind kein Ersatz für das veröffentlichte Python-Source-Archiv.

FastAPI liest die installierte Version bereits über `importlib.metadata.version`
in `atelier_api.version.software_version()`. Es gibt keine zweite Versionskonstante.
OpenAPI zeigt dieselbe installierte Softwareversion; `/api/v1` bleibt unabhängig.

Nicht getaggte Entwicklungsstände erhalten eine PEP-440-Entwicklungsversion,
einschließlich Commit-/Dirty-Informationen. Für lokale Arbeit `uv sync --locked
--dev` verwenden und nach einem Tag-Fetch erneut synchronisieren. Die
`tool.uv.cache-keys` berücksichtigen Commit und Tags. `uv.lock` fixiert weiterhin
die Abhängigkeiten, enthält aber keine statische Version des dynamischen
Root-Pakets. Release-Builds verändern weder Lockfile noch Versionsdateien.

## Conventional Commits

| Commit | Wirkung |
| --- | --- |
| `feat: …` | Minor |
| `fix: …`, `perf: …` | Patch |
| `feat!: …` oder Footer `BREAKING CHANGE: …` | Breaking |
| `docs: …`, `refactor: …`, `test: …`, `chore: …`, `ci: …` | Ohne weitere relevante Commits kein neuer Release |

Bestehende Regeln bleiben erhalten: `allow_zero_version=true`,
`major_on_zero=false`, Squash-Nachrichten werden analysiert, Merge-Commits
ignoriert. Vor 1.0 führt Breaking beispielsweise von 0.1.0 zu 0.2.0. Der Wechsel
auf eine 1.x-Policy ist eine gesonderte bewusste Änderung. Bereits veröffentlichte
Versionen werden nicht erneut gebaut oder überschrieben; Wiederholungen ohne
neue relevante Commits sind erfolgreiche No-ops (`strict: false`).

## CI und privilegierter Release-Workflow

Alle bisherigen Prüfungen bleiben: Ruff, Formatierung, mypy, pytest einschließlich
PostgreSQL-Integration, Migrationen, Paketbau und Installation in einer sauberen
Umgebung. Checkouts laden die vollständige Historie und Tags, damit dynamische
Versionen zuverlässig bestimmbar sind.

`workflow_run` akzeptiert nur erfolgreichen **Attelier CI**-Abschluss eines
ursprünglichen `push` auf `main` aus demselben Repository. PR-Code, Forks und
Tag-Pushes erhalten keinen Release-Job. Checkout und frisch gefetchter
`origin/main` müssen `workflow_run.head_sha` entsprechen. Der Guard liest diese
Git-Objekte statt einer möglicherweise irreführenden Payload-Nachricht.

Die gemeinsame Concurrency-Gruppe verhindert parallele Releases. Sie blockiert
keine normalen Pushes und garantiert keine FIFO-Reihenfolge. Veraltete Jobs
schlagen vor Veröffentlichung fehl. Ein später während des Builds eintreffender
Push ändert das Release-Ziel nicht: Der Tag zeigt weiterhin auf den bereits
geprüften Commit, niemals auf ungetesteten neueren Code. Falls GitHub einen
wartenden neueren Job ersetzt, dessen erfolgreichen aktuellen Push-CI-Lauf nach
Prüfung erneut ausführen.

Es entstehen keine Release-Commits auf `main`. Daher kann der Release selbst
keinen neuen Main-Push-CI-Lauf auslösen. Bot-Namen und Commit-Nachrichten werden
nicht pauschal ausgeschlossen. GitHub-App-Tag-Ereignisse können andere Workflows
auslösen, aber die bestehende CI hört nur auf Branches. Wiederholungen werden
zusätzlich durch bereits vorhandene Versionstags abgefangen.

Semantic Release erzeugt Release Notes und `CHANGELOG.md` im kurzlebigen
Arbeitsverzeichnis. Der Changelog wird zusammen mit Wheel und Source-Archiv am
GitHub Release angehängt; er wird nicht zurück nach `main` committed. Keine
Veröffentlichung auf PyPI. Git-Tag, GitHub Release und Assets sind getrennte
Operationen, keine atomare Transaktion.

## Authentifizierung, Regeln und GH013

Erforderlich bleiben die ausschließlich für `atelier-api` installierte App
`atelier-release-bot` mit **Contents: Read and write**, die Actions-Variable
`RELEASE_APP_CLIENT_ID` und das Secret `RELEASE_APP_PRIVATE_KEY` (vollständiger
PEM-Schlüssel). Token-Erstellung ist auf Owner und `atelier-api` beschränkt.
Checkout, Tag-Push und Assets verwenden ausschließlich diesen kurzlebigen Token;
die Action widerruft ihn am Jobende. Fehlende Credentials, ungültige App-Anmeldung
oder leere Token brechen ab. Es gibt weder PAT noch `GITHUB_TOKEN`-Fallback.
Das normale Job-Token benötigt nur `contents: read`; OIDC wird nicht verwendet.
Secrets und vollständige Payloads nicht ausgeben oder per Shell-Tracing loggen.

Bei der read-only Diagnose am 30.10.2026 enthielt das aktive Ruleset **protect
main** tatsächlich `bypass_actors: []`. Eine erfolgreiche App-Anmeldung allein
war deshalb keine Freigabe für den früheren direkten Branch-Push. Die bisherige
GH013-Meldung passte zu erzwungenen Pull Requests und fehlenden Checks auf dem neu
erzeugten Versionscommit. Es wurden keine Repository-Einstellungen verändert.

Die gewählte Architektur benötigt keinen `main`-Bypass. Falls anderweitig einer
für die App eingerichtet ist, kann ein Administrator dessen Entfernung prüfen;
der Workflow entfernt ihn nicht. Tag-Regeln müssen das Erstellen von `v*` durch
die App erlauben. Bei GH013 nun den im Fehler genannten Ref und alle darauf
wirkenden Repository-/Organisationsregeln prüfen. Checks des Ausgangscommits
belegen keine Prüfung eines hypothetischen neuen Versionscommits; ein Bypass wäre
ebenfalls kein CI-Nachweis.

## Erster Release

1. Änderung über den regulären PR-Prozess prüfen und mergen. Das kann nach
   erfolgreicher Main-CI bereits veröffentlichen: ein freigegebenes Releasefenster
   wählen. App-Installation, Variable, Secret und gegebenenfalls Tag-Regeln vorher
   kontrollieren. Weder Branch-Schutz noch erforderliche Checks abschalten.
2. Den **Attelier CI**-Push-Lauf der Merge-SHA abwarten. Der PR-CI-Lauf darf keinen
   Release starten. Bei der Diagnose waren weder lokale noch remote Tags oder
   GitHub Releases vorhanden; mit der bestehenden Feature-Historie wird 0.1.0
   erwartet. Es wird kein künstlicher Starttag angelegt.
3. Im **Semantic Release**-Lauf App-Authentifizierung, SHA-Prüfung und
   `Release guard passed.` kontrollieren. Der Release-Schritt muss `commit: false`
   verwenden. Die Version wird nicht manuell erzwungen.
4. Prüfen: `v0.1.0` zeigt auf die erfolgreiche CI-SHA; `main` hat keinen zusätzlichen
   Versionscommit; der GitHub Release enthält Release Notes, `CHANGELOG.md`,
   `atelier_api-0.1.0-py3-none-any.whl` und `atelier_api-0.1.0.tar.gz`.
5. Den Tag sauber auschecken, `uv sync --locked --no-dev` ausführen und
   `uv run --no-sync python -c 'from atelier_api.version import software_version;
   print(software_version())'` prüfen. OpenAPI muss dieselbe Version melden.
   Nach Wiederholung ohne relevante Änderungen darf kein weiterer Tag entstehen.

Keine echten Releases werden während lokaler Tests ausgelöst. Die automatisierten
Tests erzeugen ausschließlich Tags in temporären lokalen Testrepositories und
verwenden ausdrücklich `--no-push --no-vcs-release`.

## Render, Neon und Rollback

Ein Produktionsdeploy soll erst nach erfolgreicher Veröffentlichung erfolgen.
Automatisches Deployen jedes Main-Pushes kann vor dem Release-Tag passieren und
würde dann eine Entwicklungsversion installieren. Render-Autodeploys für diesen
Produktionsprozess administrativ deaktivieren und anschließend **Manual Deploy →
Deploy a specific commit** mit der SHA des veröffentlichten Tags verwenden.
Diese Render-Einstellung wird hier nicht verändert.

Ein Git-basierter Render-Build benötigt Python 3.14+, `uv` und vollständige
Release-Tags. Beispiel-Build: `git fetch --tags origin && uv sync --locked --no-dev`.
Ein sauberer Checkout muss exakt auf dem freigegebenen Tag liegen; alternativ
kann das bereits geprüfte Wheel installiert werden. Keine dauerhafte
`SETUPTOOLS_SCM_PRETEND_VERSION`-Variable auf Render setzen. Start:
`uv run --no-sync uvicorn atelier_api.main:app --host 0.0.0.0 --port "$PORT"`.
Secrets einschließlich der Neon-URL bleiben in der Deployment-Umgebung.
Migrationen werden kontrolliert über die bestehende Alembic-Konfiguration vor dem
Rollout angewendet, nicht beim Paketimport. Repository-Archive ohne Tags müssen
das veröffentlichte Wheel/Source-Archiv statt einer erfundenen Version verwenden.

Rollback: den zuvor veröffentlichten Commit beziehungsweise dessen geprüftes
Wheel deployen. Tags nie verschieben, Versionen nie wiederverwenden, kein
Force-Push. Ein Code-Rollback macht Neon-Schemaänderungen nicht rückgängig;
Migrationskompatibilität, Daten und Backups separat prüfen, bevorzugt vorwärts
korrigieren. Bei Teilfehlern zuerst feststellen, ob der Tag oder Release bereits
existiert. Fehlende Assets gezielt für diesen Tag wiederherstellen, ohne eine
neue Version zu erfinden oder alte Assets unkontrolliert zu überschreiben.

Quellen: [PSR 10.7 CLI](https://python-semantic-release.readthedocs.io/en/latest/api/commands.html),
[hatch-vcs](https://github.com/ofek/hatch-vcs),
[uv Cache-Keys](https://docs.astral.sh/uv/concepts/cache/),
[Render Deploys](https://render.com/docs/deploys).
