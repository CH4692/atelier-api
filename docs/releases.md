# Automatische Releases

## Authentifizierung und Regeln

Die App `atelier-release-bot` ist nur für `atelier-api` installiert und benötigt
**Repository Contents: Read and write**. Actions benötigt die Variable
`RELEASE_APP_CLIENT_ID` und das Secret `RELEASE_APP_PRIVATE_KEY` (vollständiger
PEM-Schlüssel). Die Token-Action erhält explizit Repository-Owner, `atelier-api`
und `permission-contents: write`; sie widerruft den kurzlebigen Installationstoken
am Jobende. Checkout, Semantic Release und Distribution-Upload verwenden
ausschließlich diesen Token. Es gibt weder PAT noch `GITHUB_TOKEN`-Fallback.
Fehlende Werte und leere Token führen zu einem ausdrücklichen Fehler; ungültige
oder nicht installierte App-Zugangsdaten lassen die Token-Action fehlschlagen.
Secrets oder Event-Payloads dürfen nicht mit Shell-Tracing ausgegeben werden.

Die App benötigt in allen zutreffenden `main`-Rulesets den Bypass **Always allow**.
**For pull requests only** genügt für den direkten Versionscommit nicht.
Gegebenenfalls geltende Tag-Regeln für `v*` müssen das Erstellen durch die App
zulassen. Der Workflow verändert keine Regeln. Reviews und CI für normale
Pull Requests bleiben unverändert. App-Schlüssel mit Bypass-Berechtigung sind
entsprechend zu schützen und bei Bedarf zu rotieren.

**Der Bypass ist keine erfolgreiche CI-Prüfung des Versionscommits.** Geprüft
ist dessen Ausgangscommit; Semantic Release erstellt danach einen neuen Commit
mit Versionsdatei, Lockfile und Changelog. Dieser kann Ruleset-Checks umgehen
und durch `[skip ci]` ohne einen eigenen Push-CI-Lauf bleiben.

## Auslöser und Release-Guard

Der Job akzeptiert nur `workflow_run` von **Attelier CI** mit erfolgreichem
Abschluss, ursprünglichem Ereignis `push`, Branch `main` und demselben
Quellrepository. Die Checkout-SHA muss der `workflow_run.head_sha` entsprechen.
Ein erneutes Fetch von `main` prüft, ob dieser getestete Stand noch aktuell ist.
Veraltete Jobs schlagen vor der Veröffentlichung fehl; es wird auf den CI-Lauf
des neueren Standes gewartet. Die Concurrency-Gruppe serialisiert Release-Jobs,
garantiert aber keine FIFO-Reihenfolge und blockiert keine normalen Pushes.
GitHub kann einen wartenden Job durch einen später eingereihten ersetzen. Falls
dadurch nach einem veralteten Lauf kein Release für den aktuellen Stand folgt,
den erfolgreichen Push-CI-Lauf der unveränderten aktuellen `main`-SHA erneut
ausführen. Nicht den alten Release-Lauf gegen einen neueren Stand erzwingen.

`workflow_run` enthält laut [GitHub-Schema](https://github.com/octokit/webhooks/blob/main/payload-schemas/api.github.com/common/workflow-run.schema.json)
unter anderem `head_sha`, `head_commit`, `actor` und `triggering_actor`.
`scripts/check_release_guard.py` liest den vollständigen Commit-Text dennoch
direkt aus dem geprüften Git-Objekt und benötigt `head_commit.message` nicht.
Der ursprüngliche `actor.login` identifiziert den CI auslösenden Akteur;
`triggering_actor` kann bei manuellen Wiederholungen eine andere Person sein.

Ein Commit wird nur dann als automatisch erzeugter Release-Commit übersprungen,
wenn alle folgenden Merkmale zutreffen:

- Ursprünglicher CI-Akteur: `atelier-release-bot[bot]`.
- Vollständiger Git-Commit-Text entspricht `commit_message` aus `pyproject.toml`,
  formatiert mit der aktuellen `project.version`.
- Genau ein Elterncommit und ausschließlich Änderungen an `pyproject.toml`,
  `uv.lock` oder `CHANGELOG.md`.

Andere Bot-Commits, nur ähnlich benannte Commits sowie Änderungen an Anwendung
oder Workflow werden dadurch nicht unterdrückt. Menschliche Wiederholungen
ändern den ursprünglichen CI-Akteur nicht. Wenn Bot-Slug, Commitvorlage oder
Release-Dateien künftig geändert werden, sind Guard und Tests mit anzupassen.

Conventional Commits, Versionsberechnung, Tag-Format, Changelog und Build-Befehl
bleiben in `pyproject.toml` unverändert. Nach dem Build pusht Semantic Release
ohne Force. Bei einem zwischenzeitlichen normalen Push auf `main` divergieren
die Historien und der Release-Push wird abgewiesen. Dann den neueren CI-Lauf
abwarten; keine Tags verschieben und keinen Force-Push ausführen. Git-Push,
Tag-Push, GitHub Release und Artefakt-Upload sind getrennte Operationen; bei
Teilfehlern zuerst den tatsächlich veröffentlichten Stand prüfen.

## GH013 prüfen

Bei `GH013` zuerst die im Fehler verlinkten Regeln lesen und prüfen:

1. Sind Variable und Secret für dieses Repository verfügbar und gehört die
   Client-ID zur installierten App `atelier-release-bot`?
2. Besitzt die App **Contents: Read and write**, und ist die Installation auf
   `atelier-api` freigeschaltet?
3. Ist genau diese App in allen betreffenden Rulesets als **Always allow**
   eingetragen? Auch Organisations-/Tag-Regeln beachten.
4. Verwenden Checkout und beide Semantic-Release-Actions denselben App-Token?

Mehr Rechte für `GITHUB_TOKEN` oder erneutes Ausführen derselben CI ersetzt den
App-Bypass nicht. Checks des Ausgangscommits gelten nicht für den Versionscommit.

## Verifikation in GitHub Actions

Diese Schritte sind für eine ausdrücklich freigegebene Prüfung nach dem Merge
vorgesehen; die lokale Implementierung führt keinen davon automatisch aus.

1. Änderungen über einen normalen Pull Request prüfen lassen und nach Freigabe
   mergen. Bereits ein Merge auf `main` kann bei relevanten vorhandenen Commits
   einen echten Release auslösen; dafür vorher ein Veröffentlichungsfenster wählen.
2. Den **Attelier CI**-Push-Lauf für die Merge-SHA öffnen und dessen erfolgreichen
   Abschluss abwarten. Der PR-Lauf darf keinen Release starten.
3. Im nachfolgenden **Semantic Release**-Lauf Token-Erstellung, SHA-Prüfung und
   `Release guard passed.` kontrollieren. Keine Secrets in Logs kopieren.
4. Bei relevantem Commit Verlauf prüfen: Versionscommit, passender `v…`-Tag,
   GitHub Release sowie Wheel und Source-Archiv. Ohne relevanten Commit ist ein
   sauberer Lauf ohne neuen Release korrekt.
5. Falls CI auf einem Versionscommit ausgeführt oder wiederholt wird, muss der
   Guard `release=false` setzen und den Release-Schritt überspringen. Bei `[skip ci]`
   entsteht gewöhnlich schon kein neuer Push-CI-Lauf.
6. Fehler-, Fremdbranch-, fehlende-Credentials- und Parallel-Push-Szenarien sind
   lokal automatisiert getestet. Solche Fehler nicht durch Entfernen produktiver
   Secrets oder zusätzliche Test-Pushes auf `main` provozieren. Live-Negativtests
   nur in einem ausdrücklich freigegebenen Testrepository mit eigener App und
   denselben Regeln durchführen.

Vor einem erneuten Lauf nach Fehlern prüfen, ob Commit, Tag oder Release bereits
existieren. Fehlende Artefakte gezielt für den existierenden Tag nachliefern;
veröffentlichte Versionen nicht überschreiben.
