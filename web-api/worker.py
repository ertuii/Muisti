"""Muisti web worker (Vercel Python function at /api/worker): runs the desktop's Core, i.e. Anki's own engine,
for the web app's rarer actions: statistics, deck options and FSRS, note types, filtered decks, import/export,
full search. Studying never comes here, it runs in the browser.

Each user's collection is a copy in /tmp, kept current with the same row sync as the desktop (muisti/cloud.py):
pull before the call, push after. A warm instance only pulls what changed; a cold one pulls everything once.
The request's Supabase token is the only credential; every read and write goes through RLS as that user.
"""

import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(tempfile.gettempdir()) / "muisti"
os.environ.setdefault("MUISTI_DIR", str(ROOT))  # Core's config.json; the collections live below it
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_lib"))

from muisti import cloud  # noqa: E402
from muisti.core import Core  # noqa: E402

# what the web may run here; studying, desktop settings, AnkiWeb and updates never
ALLOWED = {
    "statistics", "weak_spots", "difficult_cards", "card_info", "set_due_date",
    "deck_options", "save_deck_options", "overwrite_preset", "new_preset", "optimize_fsrs",
    "create_filtered_deck", "rebuild_filtered_deck", "empty_filtered_deck", "prelearn", "end_prelearn", "practice",
    "notetype", "save_notetype", "add_notetype", "delete_notetype", "preview_template", "note_types",
    "inspect_import", "import_file", "export_deck", "export_collection", "search", "apply_exam_pace",
}
# what Claude may run here through the connector (connector.py): the desktop MCP tools that touch no local files
MCP_ALLOWED = {
    "decks", "create_deck", "rename_deck", "note_types", "add_note", "add_media", "inbox", "difficult_cards",
    "weak_spots", "exam_plan", "search", "get_note", "update_note", "delete_notes", "suspend", "forget_cards",
    "card_info", "stats", "statistics", "create_filtered_deck",
}
STORAGE = "storage:"  # path arguments that name a file in the user's storage folder (uploads, exports)
MAX_CACHED = 20  # ponytail: collections kept per warm instance, oldest dropped first; /tmp is 500 MB


class TokenAccount:
    """cloud.Account's interface over the token of the current request (nothing stored on disk)."""

    def __init__(self, uid: str):
        self.state = {"user_id": uid, "device": f"worker-{secrets.token_hex(4)}", "last_usn": None}
        self.access = None

    def token(self):
        return self.access

    def load(self):
        return self.state

    def set(self, **changes):
        self.state.update(changes)


class Entry:
    def __init__(self, uid: str):
        folder = ROOT / uid
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        self.core = Core(str(folder / "collection.anki2"))
        self.account = TokenAccount(uid)
        self.lock = threading.Lock()
        self.used = time.time()


_entries: dict[str, Entry] = {}
_entries_lock = threading.Lock()


def entry_for(uid: str) -> Entry:
    with _entries_lock:
        if uid not in _entries:
            if len(_entries) >= MAX_CACHED:
                old = min(_entries, key=lambda k: _entries[k].used)
                _entries.pop(old).core._close()
                shutil.rmtree(ROOT / old, ignore_errors=True)
            _entries[uid] = Entry(uid)
        e = _entries[uid]
        e.used = time.time()
        return e


_users: dict[str, tuple[str, float]] = {}  # token -> (user id, checked until)
USER_TTL = 300  # ponytail: a revoked token works up to 5 more minutes here; Supabase tokens live an hour anyway


def user_of(token: str) -> str:
    hit = _users.get(token)
    if hit and hit[1] > time.time():
        return hit[0]
    try:
        uid = cloud._http("GET", "/auth/v1/user", token=token)["id"]
    except (cloud.CloudError, KeyError, TypeError):
        raise PermissionError("Nicht angemeldet") from None
    if len(_users) > 1000:
        _users.clear()
    _users[token] = (uid, time.time() + USER_TTL)
    return uid


# ---------- files: uploads come in through storage, exports go out the same way ----------

def _object(uid: str, name: str) -> str:
    return f"/storage/v1/object/media/{uid}/_tmp/{urllib.parse.quote(name)}"


def fetch_file(token: str, uid: str, name: str, folder: Path) -> str:
    target = folder / re.sub(r"^[0-9a-f]{8}-", "", Path(name).name)  # the web's upload prefix; the name becomes a deck name
    target.write_bytes(cloud._http("GET", _object(uid, name).replace("/object/", "/object/authenticated/", 1), token=token))
    return str(target)


def put_file(token: str, uid: str, name: str, path: str):
    cloud._http("POST", _object(uid, name), Path(path).read_bytes(), token,
                {"Content-Type": "application/octet-stream", "x-upsert": "true"})


def upload_new_media(core: Core, token: str, uid: str, before: set[str]):
    folder = Path(core.media_dir())
    for name in sorted(set(os.listdir(folder)) - before):
        if (folder / name).is_file() and not name.startswith("."):
            cloud._http("POST", f"/storage/v1/object/media/{uid}/{urllib.parse.quote(name)}", (folder / name).read_bytes(),
                        token, {"Content-Type": "application/octet-stream", "x-upsert": "true"})


MEDIA_REF = re.compile(r"""(?:src=["']([^"']+)["'])|\[sound:([^\]]+)\]""")


def fetch_media_for(core: Core, token: str, uid: str, deck_id: int | None):
    """An export with media needs the files of the exported notes, which a worker copy doesn't keep."""
    col = core._col
    nids = col.find_notes(f"did:{deck_id}" if deck_id else "")
    folder = Path(core.media_dir())
    names = set()
    for nid in nids:
        for m in MEDIA_REF.finditer(col.get_note(nid).joined_fields()):
            names.add(urllib.parse.unquote(m.group(1) or m.group(2)))
    for name in names:
        if "/" in name or ":" in name or (folder / name).exists():
            continue
        try:
            data = cloud._http("GET", f"/storage/v1/object/authenticated/media/{uid}/{urllib.parse.quote(name)}", token=token)
            (folder / name).write_bytes(data)
        except cloud.CloudError:
            pass  # referenced but never uploaded: Anki exports without it too


def run(token: str, method: str, args: list | dict, allowed: set[str] = ALLOWED):
    """args: positional from the web app, keywords from the connector (which has no storage: paths)."""
    if method not in allowed and method != "warm":
        raise ValueError(f"Gibt es im Web nicht: {method}")
    uid = user_of(token)
    e = entry_for(uid)
    with e.lock:
        e.account.access = token
        cloud.sync(e.core._col, e.account)
        e.core.mix_subdecks_by_default()  # after the pull: a fresh copy only has the user's presets now
        if method == "warm":  # the web app opening: load the collection here before the first real call needs it
            return None
        tmp = Path(tempfile.mkdtemp())
        try:
            exports = []  # (storage name, local path)
            uploads = []
            for i, a in enumerate(args if isinstance(args, list) else []):
                if isinstance(a, str) and a.startswith(STORAGE):
                    name = a[len(STORAGE):]
                    if method.startswith("export_"):
                        args[i] = str(tmp / Path(name).name)
                        exports.append((name, args[i]))
                    else:
                        args[i] = fetch_file(token, uid, name, tmp)
                        uploads.append(name)
            if method == "export_deck" or method == "export_collection":
                fetch_media_for(e.core, token, uid, args[1] if method == "export_deck" and len(args) > 1 else None)
            media_before = set(os.listdir(e.core.media_dir()))
            result = getattr(e.core, method)(**args) if isinstance(args, dict) else getattr(e.core, method)(*args)
            upload_new_media(e.core, token, uid, media_before)
            for name, path in exports:
                put_file(token, uid, name, path)
            if not method.startswith("inspect_"):  # the import dialog inspects first, then imports the same file
                for name in uploads:
                    try:
                        cloud._http("DELETE", _object(uid, name), token=token)
                    except cloud.CloudError:
                        pass  # a leftover upload must not keep the import from being pushed
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        cloud.sync(e.core._col, e.account, pull=False)
        return result


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        token = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            body, status = {"result": run(token, req.get("method", ""), list(req.get("args", [])))}, 200
        except PermissionError as err:
            body, status = {"error": str(err)}, 401
        except Exception as err:  # the UI shows the message, as on the desktop; the log keeps the details
            import traceback

            traceback.print_exc()
            body, status = {"error": str(err) or type(err).__name__}, 200
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
