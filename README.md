# Muisti

Anki-Klon für macOS und Windows mit ruhigem, modernem UI und MCP-Server für Claude.

> **Früher BetterAnki?** Muisti einmal neu laden und öffnen: Beim ersten Start zieht es Karten, Einstellungen und Sicherungen aus dem BetterAnki-Ordner um und stellt die Claude-Verbindung um. Die alte BetterAnki-App danach löschen.
Unter der Haube läuft Ankis offizieller Kern (`anki` von PyPI): gleiche Planung (SM-2/FSRS), gleiche Dateiformate (.apkg), gleiche Suchsyntax.

Deine Daten liegen lokal, standardmäßig hier (änderbar unter *Einstellungen → Speicherort*):
- macOS: `~/Library/Application Support/Muisti/`
- Windows: `%APPDATA%\Muisti\`

## Funktionen

- **Heute:** fällige Karten, Semesterstreifen (Lernverlauf + Prognose; Klick auf einen künftigen Tag lernt dessen Karten vor), Stapel mit Unterstapeln
- **Lernen:** Tastatur (Leertaste, 1–4), Bearbeiten, Rückgängig, Zurückstellen, Audio, Vorlesen (`{{tts de_DE:Feld}}`), Formeln (`\(…\)`, `\[…\]` mit KaTeX), Antwort eintippen (`{{type:Feld}}`)
- **Hinzufügen / Browser:** Rich-Text-Felder, Lückentext, Bild-Verdeckung (Bereiche auf einem Bild aufziehen), Hinweis auf Dubletten, Suche mit Anki-Syntax, Filter nach Stapel und Status, Aussetzen, Markieren, Verschieben
- **Stapel-Optionen:** alle Optionen von Anki – Voreinstellungen, Tageslimits (auch nur für diesen Stapel / nur heute), Lernschritte, Lästlinge, Anzeigereihenfolge, Zurückstellen, Audio, Timer, Automatisch weiter, Leichte Tage, SM-2-Faktoren, **FSRS** inkl. Optimierung
- **Gefilterte Stapel:** Karten per Suche zum Pauken sammeln
- **Statistik:** Wiederholungen, Prognose, Kartenzahlen, Intervalle, Tageszeit, Erinnerung, Antworttasten
- **Notiztypen:** Felder, Kartenvorlagen und CSS bearbeiten, mit Live-Vorschau
- **Von Anki umziehen:** erkennt Anki-Profile auf dem Rechner und übernimmt sie mit Lernstand und Medien (ersetzen oder hinzufügen); Anki bleibt unverändert
- **Einstellungen:** Sprache (Deutsch, English, Español), Ankis globale Einstellungen (Tageswechsel, Vorauslernen, Zeitlimit, Anzeige, Lastverteilung, Editor, Sicherungsintervalle), optionale AnkiWeb-Synchronisierung, automatische Sicherungen + Wiederherstellen, Export der ganzen Sammlung, Claude-Befehl zum Kopieren
- **Import/Export:** `.apkg`, `.colpkg`, CSV (mit Vorschau, Stapel- und Spaltenwahl), auch per Drag & Drop ins Fenster

- **Eingang für Claude-Karten:** Karten, die Claude anlegt, warten ausgesetzt im Eingang, bis du sie übernimmst, bearbeitest oder verwirfst (abschaltbar)

**Zusatzfunktionen** (gibt es in Anki nicht, einzeln einschaltbar unter *Einstellungen → Zusatzfunktionen*):

- **Prüfungstermine:** eigene Seite *Prüfungen*, Klausurdatum pro Stapel; die App rechnet aus, wie viele neue Karten pro Tag nötig sind (die letzten Tage bleiben fürs Wiederholen) und markiert die Prüfung im Zeitstrahl
- **Lernplan:** Dauer wählen und über alle Stapel lernen, nahe Prüfungen zuerst
- **Schwachstellen:** Themen und Stapel unter deinem Durchschnitt in der Statistik, mit „Üben“ für die vergessenen Karten

Noch nicht: Add-ons.

## Starten (Entwicklung)

```sh
brew install uv            # einmalig (Windows: winget install astral-sh.uv)
cd ui && npm install && npm run build && cd ..
uv run muisti
```

## App bauen

```sh
uv run python build.py     # -> dist/Muisti.app (Mac) bzw. dist/Muisti/Muisti.exe (Windows)
```
PyInstaller baut nur für das System, auf dem es läuft. Die Windows-Version entsteht auf einem Windows-PC oder über GitHub Actions (`.github/workflows/build.yml`).

## Updates ausrollen

1. Version in `src/muisti/__init__.py` und `pyproject.toml` erhöhen (z. B. `0.3.0`), committen.
2. `git tag v0.3.0 && git push --tags`
3. GitHub Actions baut Mac und Windows und veröffentlicht ein Release mit `Muisti-macOS.zip` und `Muisti-Windows.zip`.
4. Installierte Apps sehen beim Start „Version 0.3.0 ist da“, ein Klick lädt, ersetzt und startet die App neu. Karten liegen getrennt und bleiben unberührt.

Das Release muss ohne Anmeldung abrufbar sein, das Repo also öffentlich.
Erste Installation bei Freunden (App ist nicht signiert): Mac – App einmal öffnen, dann *Systemeinstellungen → Datenschutz & Sicherheit → Trotzdem öffnen* (nur Apple-Silicon-Macs, der CI-Build ist arm64); Windows – „Weitere Informationen“ → *Trotzdem ausführen*. Updates danach brauchen das nicht mehr.

## Webapp & Muisti-Konto

Muisti gibt es auch im Browser (Vercel), mit Konto (Supabase Auth). Die Karten liegen dann zusätzlich online, Zeile für Zeile wie in Ankis Datenbank (`supabase/migrations/`), jede Person sieht nur ihre eigenen (RLS).

- **Desktop:** *Einstellungen → Muisti-Konto* anmelden. Muisti gleicht beim Start, alle 5 Minuten und beim Beenden ab. Ankis Regel: Die neuere Änderung gewinnt, gelöschte Karten verschwinden überall, Wiederholungen werden zusammengeführt. AnkiWeb-Sync und Muisti-Konto schließen sich aus.
- **Web:** alles außer den reinen Desktop-Dingen (Sicherungen, Speicherort, AnkiWeb, Von Anki übernehmen; stattdessen .colpkg importieren). Lernen, Hinzufügen, Browser, Prüfungen und Lernplan laufen im Browser (FSRS über ts-fsrs bzw. SM-2, Limits auch übergeordneter Stapel, Geschwister zurückstellen). Was Ankis eigene Engine braucht – Statistik, Stapel-Optionen und FSRS-Optimierung, Notiztypen, gefilterte Stapel, Vorlernen/Üben, Import/Export, die volle Suche (ODER, Klammern, Feldsuche) – erledigt der **Worker** (`web-api/worker.py`, Vercel-Funktion): Er führt `core.py` selbst aus, auf einer Kopie der Sammlung, die er per Sync holt und zurückschreibt.
- Entwicklung: `cd ui && npm run build:web && npx vite preview --mode web --outDir dist-web`, dazu den Worker mit `PYTHONPATH=src uv run python web-api/dev.py` (Supabase-Projekt steht in `ui/.env.web`).

**Updates:** Der Tag `v<version>` (siehe *Updates ausrollen*) baut auch die Webapp und stellt sie auf Vercel online; offene Tabs zeigen dann „Aktualisieren“. Einmalig nötig:
1. GitHub-Secret `VERCEL_TOKEN` (vercel.com → Account Settings → Tokens).
2. Supabase → Authentication → URL Configuration: *Site URL* = Adresse der Webapp (für Bestätigungs- und Passwort-Mails).
3. Für Claude im Web: Supabase → Authentication → OAuth Server einschalten, *Authorization Path* `/oauth/consent`, *Dynamic Client Registration* an.
4. Optional: Secrets `MUISTI_TEST_EMAIL`/`MUISTI_TEST_PASSWORD` (ein bestätigtes Testkonto), dann läuft `tests/test_cloud.py` auch in CI. Achtung: der Test leert die Online-Daten dieses Kontos.

Datenbank-Änderungen kommen als neue Datei nach `supabase/migrations/` und werden vor dem Tag eingespielt (`supabase db push`). Nur ergänzen, nichts umbenennen: ältere Apps synchronisieren weiter. Geht es nicht anders, `sync_state.schema` erhöhen, dann bitten ältere Apps um ein Update statt zu synchronisieren.

## Website

Die Download-Seite liegt komplett in `site/` (statisches HTML, kein Build) und hat mit der App nichts zu tun. `.github/workflows/pages.yml` veröffentlicht sie auf GitHub Pages, sobald sich etwas in `site/` ändert.
Einmalig im Repo: *Settings → Pages → Source: GitHub Actions*. Die Download-Buttons zeigen immer auf das neueste Release.

## Claude anbinden (MCP)

In der App: **Einstellungen → Claude verbinden → Verbinden** (für Claude Desktop und/oder Claude Code). Das war's; Claude Desktop danach einmal neu starten. Verschiebst du die App später, trägt sie den neuen Pfad beim nächsten Start selbst nach.

Läuft die App, schreibt Claude direkt in die offene Sammlung (neue Karten erscheinen sofort im Eingang). Ist sie geschlossen, öffnet der MCP-Server die Sammlung selbst.

Tools: `list_decks`, `create_deck`, `rename_deck`, `list_note_types`, `add_notes` (lehnt Dubletten ab), `add_media`, `current_card`, `search_cards`, `get_note`, `update_note`, `delete_notes`, `suspend_cards`, `card_info`, `collection_stats`, `review_statistics`, `create_filtered_deck`, `import_file`, `export_deck`, `list_inbox`, `difficult_cards`, `weak_spots`, `exam_plan`.

Fertige Abläufe (MCP-Prompts): **Karten aus Material erstellen** (Skript, PDF oder Text → Karten, ohne Dubletten) und **Schwierige Karten verbessern** (oft vergessene Karten analysieren und nach deinem OK umformulieren).

Für andere MCP-Clients steht der Startbefehl unter *Einstellungen → Claude verbinden → Andere MCP-Clients*.

**Online (claude.ai, Claude-App auf dem Handy):** In Claude unter *Einstellungen → Konnektoren* einen eigenen Konnektor mit `https://app.muisti.de/mcp` hinzufügen, mit dem Muisti-Konto anmelden, „Zulassen“. Das ist `web-api/connector.py`: dieselben Tools über den Worker, ohne die, die lokale Dateien brauchen (`current_card`, `import_file`, `export_deck`; `add_media` nur per URL oder Base64). Anmeldung über Supabase Auth als OAuth-2.1-Server, Zustimmungsseite `/oauth/consent`. Nutze in einem Claude nur eine der beiden Verbindungen: lokal ist die Sammlung auf dem Laptop, online das Konto; dazwischen liegt der Sync (bis zu 5 Minuten).

## Tastatur

Unter Windows `Strg` statt `⌘`.

- **Heute:** `Leertaste` lernen, `A` hinzufügen
- **Lernen:** `Leertaste`/`↵` aufdecken, danach Gut · `1–4` bewerten · `E` bearbeiten · `-` zurückstellen · `@` Karte aussetzen · `!` Notiz aussetzen · `A` automatisch weiter · `⌘Z` rückgängig · `Esc` zurück
- **Editor:** `⌘↵` speichern · `⌘⇧C` Lückentext · `⌘V` Bild einfügen · `Esc` abbrechen
- **Bild-Verdeckung:** Bereich auswählen, `⌫` löscht ihn
- **Browser:** `⌘A` alle auswählen · `⌘`+Klick mehrere auswählen

## Test

```sh
for t in tests/test_*.py; do uv run python $t || break; done   # test_cloud.py braucht MUISTI_TEST_EMAIL/-PASSWORD
cd ui && npm run check && npm test
```

Lizenz: AGPL-3.0 (wie Anki).
