"""MCP stdio server. Forwards to the running app (the collection is exclusively locked),
or opens the collection itself for the duration of one call when the app is closed."""

import base64
import json
import threading
import urllib.request
from pathlib import Path

from mcp.server import MCPServer

from .core import Core
from .server import INFO_FILE

# the user may also have the web connector (web-api/connector.py) in the same Claude: say which collection this is
mcp = MCPServer("Muisti", instructions=(
    "Muisti on this computer: the collection in the desktop app on this laptop. If a second Muisti connector (online) "
    "is also available, it holds the same cards; changes reach the other side only after the app's "
    "next sync (up to 5 minutes)."))
_open_lock = threading.Lock()  # tool calls run in parallel threads; the collection opens once at a time


def call(method: str, **args):
    try:
        info = json.loads(INFO_FILE.read_text())
        req = urllib.request.Request(
            f"http://127.0.0.1:{info['port']}/rpc",
            data=json.dumps({"method": method, "args": args}).encode(),
            headers={"X-Token": info["token"], "Content-Type": "application/json"},
        )
        body = json.loads(urllib.request.urlopen(req, timeout=60).read())
    except (FileNotFoundError, ConnectionError, urllib.error.URLError):
        with _open_lock:
            core = Core()  # app not running
            try:
                return getattr(core, method)(**args)
            finally:
                core._close()
    if "error" in body:
        raise RuntimeError(body["error"])
    return body["result"]


@mcp.tool()
def list_decks() -> list[dict]:
    """All decks as a tree with new/learn/review counts due today."""
    return call("decks")


@mcp.tool()
def create_deck(name: str) -> int:
    """Create a deck (use '::' for subdecks, e.g. 'Spanisch::Verben'). Returns the deck id."""
    return call("create_deck", name=name)


@mcp.tool()
def rename_deck(deck_id: int, name: str) -> None:
    """Rename a deck."""
    return call("rename_deck", deck_id=deck_id, name=name)


@mcp.tool()
def list_note_types() -> list[dict]:
    """Note types with their field names (the keys of a note's "fields")."""
    return call("note_types")


@mcp.tool()
def add_notes(notes: list[dict]) -> list:
    """Add notes in bulk. Each note: {"deck": "Deck::Name", "notetype": "Basic", "fields": {"Front": "...", "Back": "..."}, "tags": ["a"]}.
    Fields may contain HTML. For cloze use notetype "Cloze" with {"Text": "{{c1::Berlin}} ist die Hauptstadt"}.
    Images/audio: a stored media file appears in a field as <img src="NAME"> or [sound:NAME].
    A note whose first field already exists in a note of the same type is rejected as a duplicate (the error names
    that note); "allow_duplicate": true skips this check.
    Unless the user turned it off, new notes wait in the app's inbox ("Eingang") until the user accepts them.
    Returns the new note id, or an error string, per note."""
    results = []
    for n in notes:
        try:
            results.append(call("add_note", notetype=n.get("notetype", "Basic"), deck=n["deck"], fields=n["fields"],
                                tags=n.get("tags", []), inbox=True, allow_duplicate=bool(n.get("allow_duplicate"))))
        except Exception as e:
            results.append(f"error: {e}")
    return results


@mcp.tool()
def add_media(filename: str, path: str | None = None, url: str | None = None, data_base64: str | None = None) -> str:
    """Store an image or audio file (e.g. a diagram from a PDF) in the collection's media folder.
    Exactly one source: an absolute local path, an http(s) URL, or base64 data. filename sets the name and extension.
    Returns the stored file name (may differ if the name was taken), for <img src="NAME"> or [sound:NAME] in a field."""
    if path:
        if not Path(path).is_file():
            raise ValueError(f"no such file: {path}")
        data_base64 = base64.b64encode(Path(path).read_bytes()).decode()
    elif url:
        if not url.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        req = urllib.request.Request(url, headers={"User-Agent": "Muisti"})
        data_base64 = base64.b64encode(urllib.request.urlopen(req, timeout=30).read()).decode()
    if not data_base64:
        raise ValueError("give path, url or data_base64")
    return call("add_media", filename=filename, data_b64=data_base64)


@mcp.tool()
def current_card() -> dict | None:
    """The card the user is studying in the app right now: fields, rendered question/answer text, deck, lapses.
    null if they aren't studying. Edits to this note show on the study screen right away."""
    return call("current_card")


@mcp.tool()
def list_inbox() -> list[dict]:
    """Notes Claude created that the user has not accepted yet (they are suspended until then)."""
    return call("inbox")


@mcp.tool()
def difficult_cards(deck: str | None = None, limit: int = 20) -> list[dict]:
    """Cards the user keeps forgetting (2+ lapses or leech), most lapses first, with full fields."""
    return call("difficult_cards", deck=deck, limit=limit)


@mcp.tool()
def weak_spots(days: int = 90) -> dict:
    """Retention per tag and per deck over the last days, weakest first (only groups with 10+ reviews)."""
    return call("weak_spots", days=days)


@mcp.tool()
def exam_plan() -> list[dict]:
    """Exam dates the user set per deck, days left, new cards left and the new cards per day needed."""
    return call("exam_plan")


@mcp.tool()
def search_cards(query: str = "", limit: int = 100) -> list[dict]:
    """Search with Anki syntax: 'deck:Spanisch', 'tag:verb', 'is:due', 'is:new', 'is:suspended', 'prop:ivl>30', 'rated:7', 'front:*haus*', free text. Empty = all."""
    return call("search", query=query, limit=limit)


@mcp.tool()
def get_note(note_id: int) -> dict:
    """Full note: fields, tags, deck, card ids."""
    return call("get_note", note_id=note_id)


@mcp.tool()
def update_note(note_id: int, fields: dict | None = None, tags: list[str] | None = None, deck: str | None = None) -> None:
    """Change some fields, replace the tag list, and/or move the note's cards to another deck."""
    return call("update_note", note_id=note_id, fields=fields, tags=tags, deck=deck)


@mcp.tool()
def delete_notes(note_ids: list[int]) -> int:
    """Delete notes and their cards. Returns number deleted."""
    return call("delete_notes", note_ids=note_ids)


@mcp.tool()
def suspend_cards(card_ids: list[int], suspended: bool = True) -> None:
    """Suspend (or unsuspend) cards."""
    return call("suspend", card_ids=card_ids, suspended=suspended)


@mcp.tool()
def reset_cards(card_ids: list[int]) -> int:
    """Reset cards to new, erasing their study progress."""
    return call("forget_cards", card_ids=card_ids)


@mcp.tool()
def card_info(card_id: int) -> str:
    """Review history and scheduling details of a card (HTML)."""
    return call("card_info", card_id=card_id)


@mcp.tool()
def collection_stats() -> dict:
    """Total cards/notes, cards due today, what was studied today."""
    return call("stats")


@mcp.tool()
def review_statistics(deck_id: int | None = None, days: int = 30) -> dict:
    """Study statistics: today's answers, reviews per day, forecast of due cards, card counts by state,
    interval distribution, answer buttons, true retention. days: 30, 90 or 365."""
    return call("statistics", deck_id=deck_id, days=days)


@mcp.tool()
def create_filtered_deck(name: str, search: str, limit: int = 100) -> int:
    """Gather cards matching an Anki search into a temporary study deck (e.g. 'deck:Statistik is:due' for cramming)."""
    return call("create_filtered_deck", name=name, search=search, limit=limit)


@mcp.tool()
def import_file(path: str) -> str:
    """Import an .apkg or .csv/.txt/.tsv file from an absolute path. A .colpkg replaces the whole collection."""
    return call("import_file", path=path)


@mcp.tool()
def export_deck(path: str, deck_id: int | None = None) -> int:
    """Export a deck (or everything if no deck_id) as .apkg to an absolute path."""
    return call("export_deck", path=path, deck_id=deck_id)


# ---------- ready-made workflows (prompts) ----------

@mcp.prompt(title="Karten aus Material erstellen")
def karten_aus_material(material: str, deck: str = "") -> str:
    """Turn lecture notes, a script, a PDF or a pasted text into flashcards."""
    target = f'in den Stapel "{deck}"' if deck else "in einen passenden Stapel (frag nach, wenn unklar)"
    return f"""Erstelle Lernkarten aus diesem Material {target}:

{material}

So gehst du vor:
1. Ist das ein Dateipfad oder Link, lies den Inhalt. Verschaff dir einen Überblick über die Kernaussagen.
2. Sieh mit list_decks und search_cards nach, was es schon gibt, damit keine Dubletten entstehen.
3. Schreib atomare Karten: eine Frage, eine Antwort, so kurz wie möglich. Fakten und Definitionen gern als
   Lückentext (Notiztyp "Cloze"), Zusammenhänge und "Warum"-Fragen als Basic. Keine Aufzählungen auf der Rückseite;
   lieber mehrere Karten. Fachbegriffe in beide Richtungen nur, wenn das sinnvoll ist.
4. Vergib Tags nach Thema bzw. Kapitel (ohne Leerzeichen, z. B. Kapitel_3).
5. Lege alles in einem add_notes-Aufruf an. Die Karten landen im Eingang der App; sag dem Nutzer, dass er sie
   dort prüft und übernimmt. Fasse kurz zusammen, wie viele Karten zu welchen Themen entstanden sind."""


@mcp.prompt(title="Schwierige Karten verbessern")
def schwierige_karten_verbessern(deck: str = "") -> str:
    """Find cards that keep being forgotten and rewrite them so they stick."""
    scope = f'im Stapel "{deck}"' if deck else "in allen Stapeln"
    return f"""Hilf mir mit den Karten, die ich {scope} immer wieder vergesse.

1. Hol sie mit difficult_cards{f'(deck="{deck}")' if deck else ''}. Schau auch auf weak_spots für Themen mit schlechter Erinnerung.
2. Finde für jede Karte den wahrscheinlichen Grund: zu viel auf einmal, unklare Frage, Verwechslung mit ähnlichen
   Karten, reines Auswendiglernen ohne Verständnis.
3. Schlag konkrete Verbesserungen vor: aufteilen, präziser fragen, Lückentext, Eselsbrücke, Beispiel oder Kontext
   ergänzen. Zeig mir alt und neu nebeneinander, gruppiert nach Grund.
4. Ändere erst nach meinem OK: bestehende Karten mit update_note (der Lernstand bleibt erhalten), zusätzliche
   Karten beim Aufteilen mit add_notes."""


def run():
    mcp.run()
