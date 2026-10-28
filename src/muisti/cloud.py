"""Muisti account: sign in to Supabase and sync the collection row by row with the web app.

Anki marks local changes with usn = -1 and deletions in `graves`. Pull fetches everything other devices wrote since the
last sync, push sends the local rows as plain upserts (the database keeps the newer `mod`, see supabase/migrations). Same ids on both sides merge cleanly, so even a first sync of two filled collections just merges.
"""

import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

URL = "https://zxrlbjtokqbxnbozelsp.supabase.co"
KEY = "sb_publishable_m9iTnduMJWje6cwY8RMutw_X_WthQxW"  # publishable: safe in the app, access is limited by RLS
SCHEMA = 1  # matches sync_state.schema; a newer schema online means this app is too old to sync
PAGE = 500

NOTE_COLS = ["id", "guid", "mid", "mod", "tags", "flds", "sfld", "csum", "flags", "data"]
CARD_COLS = ["id", "nid", "did", "ord", "mod", "type", "queue", "due", "ivl", "factor", "reps", "lapses", "left",
             "odue", "odid", "flags", "data"]
REVLOG_COLS = ["id", "cid", "ease", "ivl", "lastIvl", "factor", "time", "type"]

# The browser page after Google sign-in, in the app's colors (ui/src/app.css) and Consent.svelte's layout.
_DONE_PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Muisti</title><style>
:root{{--paper:#fbfaf7;--ink:#1c1d21;--muted:#5d5b55;--ok:#1e9452;--bad:#d93a28;color-scheme:light dark}}
@media (prefers-color-scheme:dark){{:root{{--paper:#17181b;--ink:#ecebe6;--muted:#a9a69e;--ok:#45c07c;--bad:#f0624f}}}}
body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px 16px;box-sizing:border-box;
background:var(--paper);color:var(--ink);font:16px/1.5 system-ui,-apple-system,sans-serif}}
.box{{width:min(400px,100%);display:flex;flex-direction:column;gap:14px}}
.mark{{width:44px;height:44px;border-radius:50%;display:grid;place-items:center;font-size:24px;font-weight:700;
color:#fff;background:var(--ok)}}.err{{background:var(--bad)}}
h1{{font-size:26px;font-weight:750;letter-spacing:-.02em;margin:8px 0 0}}p{{margin:0;color:var(--muted)}}
</style><main class=box><div class="mark{cls}">{mark}</div><h1>{title}</h1><p>{text}</p></main>"""


class CloudError(Exception):
    pass


def _http(method: str, path: str, body=None, token: str | None = None, headers: dict | None = None):
    import ssl

    import certifi  # the frozen app can't find the system's root certificates (see updater._get)

    data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
    base = {"apikey": KEY, "Authorization": f"Bearer {token or KEY}"}
    if data is not None:  # Supabase rejects a JSON content type without a body (e.g. on DELETE)
        base["Content-Type"] = "application/json"
    req = urllib.request.Request(URL + path, data=data, method=method, headers={**base, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context(cafile=certifi.where())) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")
        try:
            j = json.loads(msg)
            msg = j.get("msg") or j.get("message") or j.get("error_description") or j.get("error") or msg
        except ValueError:
            pass
        raise CloudError(_german(str(msg))) from None
    except OSError as e:
        raise CloudError(f"Keine Verbindung zum Muisti-Konto: {e}") from None
    return json.loads(raw) if raw and raw[:1] in b"[{" else raw


def _german(msg: str) -> str:
    return {
        "Invalid login credentials": "E-Mail oder Passwort stimmt nicht.",
        "Email not confirmed": "Bitte bestätige zuerst deine E-Mail (Link im Postfach).",
        "User already registered": "Für diese E-Mail gibt es schon ein Konto.",
    }.get(msg, msg)


class Account:
    """The signed-in account, kept in account.json next to the app data (like AnkiWeb's sync.json)."""

    def __init__(self, folder: Path):
        self.file = folder / "account.json"

    def load(self) -> dict | None:
        return json.loads(self.file.read_text()) if self.file.exists() else None

    def _save(self, d: dict):
        self.file.write_text(json.dumps(d))
        self.file.chmod(0o600)  # the refresh token is a login

    def _store_session(self, s: dict, old: dict | None = None):
        self._save({**(old or {"device": "desktop-" + secrets.token_hex(4), "last_usn": None}),
                    "email": s["user"]["email"], "user_id": s["user"]["id"], "access_token": s["access_token"],
                    "refresh_token": s["refresh_token"], "expires_at": time.time() + s["expires_in"] - 60})

    def login(self, email: str, password: str) -> str:
        self._store_session(_http("POST", "/auth/v1/token?grant_type=password", {"email": email, "password": password}))
        return email

    def login_google(self, timeout: int = 300) -> str:
        """Sign in with Google in the system browser (PKCE), Supabase sends the code back to a one-off local port."""
        import base64
        import hashlib
        import webbrowser
        from http.server import BaseHTTPRequestHandler, HTTPServer

        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        got = {}

        class Back(BaseHTTPRequestHandler):
            def do_GET(self):
                got.update(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
                ok = "code" in dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
                body = _DONE_PAGE.format(
                    mark="✓" if ok else "!", cls="" if ok else " err",
                    title="Angemeldet" if ok else "Anmeldung fehlgeschlagen",
                    text="Du kannst dieses Fenster schließen und zu Muisti zurückkehren." if ok
                    else "Schließe dieses Fenster und versuche es in Muisti erneut.").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), Back)
        srv.timeout = timeout
        q = urllib.parse.urlencode({"provider": "google", "redirect_to": f"http://127.0.0.1:{srv.server_address[1]}/",
                                    "code_challenge": challenge, "code_challenge_method": "s256"})
        webbrowser.open(f"{URL}/auth/v1/authorize?{q}")
        try:
            srv.handle_request()  # ponytail: one request; a stray favicon hit first just means "try again"
        finally:
            srv.server_close()
        if "code" not in got:
            raise CloudError(got.get("error_description") or "Google-Anmeldung abgebrochen oder abgelaufen.")
        s = _http("POST", "/auth/v1/token?grant_type=pkce", {"auth_code": got["code"], "code_verifier": verifier})
        self._store_session(s)
        return s["user"]["email"]

    def register(self, email: str, password: str) -> bool:
        """True if signed in right away, False if Supabase first sends a confirmation mail."""
        s = _http("POST", "/auth/v1/signup", {"email": email, "password": password})
        if s.get("access_token"):
            self._store_session(s)
            return True
        return False

    def logout(self):
        self.file.unlink(missing_ok=True)

    def token(self) -> str:
        d = self.load()
        if not d:
            raise CloudError("Nicht beim Muisti-Konto angemeldet")
        if time.time() > d["expires_at"]:
            try:
                self._store_session(_http("POST", "/auth/v1/token?grant_type=refresh_token", {"refresh_token": d["refresh_token"]}), d)
            except CloudError as e:
                raise CloudError(f"Anmeldung abgelaufen, bitte neu anmelden ({e})") from None
            d = self.load()
        return d["access_token"]

    def set(self, **changes):
        self._save({**self.load(), **changes})


# ---------- sync ----------

def _upsert(token: str, table: str, rows: list[dict], ignore: bool = False):
    for i in range(0, len(rows), PAGE):
        _http("POST", f"/rest/v1/{table}", rows[i:i + PAGE], token,
              {"Prefer": f"resolution={'ignore' if ignore else 'merge'}-duplicates,return=minimal"})


def _pull(token: str, table: str, since: int, device: str) -> list[dict]:
    out, after = [], since
    while True:
        q = urllib.parse.urlencode({"usn": f"gt.{after}", "device": f"neq.{device}", "order": "usn", "limit": PAGE})
        page = _http("GET", f"/rest/v1/{table}?{q}", token=token)
        out += page
        if len(page) < PAGE:
            return out
        after = page[-1]["usn"]


def _push(col, token: str, device: str, crt: bool) -> int:
    """Send local changes (usn = -1) and deletions. Returns the number of rows sent."""
    where = " where usn = -1"
    now = int(time.time())
    sent = 0

    def rows(sql, cols):
        return [dict(zip(cols, r)) for r in col.db.all(sql)]

    notes = rows(f"select {', '.join(NOTE_COLS)} from notes{where}", NOTE_COLS)
    cards = rows(f"select {', '.join(CARD_COLS)} from cards{where}", CARD_COLS)
    revlog = rows(f"select {', '.join(REVLOG_COLS)} from revlog{where}", REVLOG_COLS)
    for r in revlog:
        r["last_ivl"] = r.pop("lastIvl")
    for r in notes:
        r["sfld"] = str(r["sfld"])  # integer when the sort field is a number (see Anki's schema)
    decks = [{"id": i, "data": col.decks.get(i)} for i in col.db.list(f"select id from decks{where}")]
    confs = [{"id": i, "data": col.decks.get_config(i)} for i in col.db.list(f"select id from deck_config{where}")]
    nts = [{"id": i, "data": col.models.get(i)} for i in col.db.list(
        f"select id from notetypes{where} union select ntid from templates{where}")]
    for r in decks + confs + nts:
        r["mod"] = r["data"].get("mod") or now
    config = [{"key": k, "mod": m, "val": json.loads(bytes(v))} for k, m, v in col.db.all(f"select key, mtime_secs, val from config{where} and key != ?", GONE_NOTETYPES)]
    if crt:  # due days of reviews count from the collection's creation day: the web needs it
        config.append({"key": "_crt", "mod": 0, "val": col.crt})

    # Anki keeps no grave for note types; Core.delete_notetype notes them here
    for i in col.get_config(GONE_NOTETYPES, []):
        nts.append({"id": i, "mod": now, "deleted": True})
    tomb = {0: cards, 1: notes, 2: decks}
    for oid, kind in col.db.all("select oid, type from graves where usn = -1"):
        if kind in tomb:
            tomb[kind].append({"id": oid, "mod": now, "deleted": True})

    for table, data, ignore in (("deck_configs", confs, False), ("decks", decks, False), ("notetypes", nts, False),
                                ("config", config, False), ("notes", notes, False), ("cards", cards, False),
                                ("revlog", revlog, True)):
        if data:
            # PostgREST needs the same keys in every row of a batch
            keys = set().union(*data)
            for r in data:
                r["device"] = device
                r.setdefault("deleted", False)
                for k in keys - r.keys():
                    r[k] = None
            _upsert(token, table, data, ignore)
            sent += len(data)

    for t in LOCAL_TABLES + ("templates",):
        col.db.execute(f"update {t} set usn = 0 where usn = -1")
    col.db.execute("delete from graves where usn = -1")
    if col.get_config(GONE_NOTETYPES, None) is not None:
        col.remove_config(GONE_NOTETYPES)
    return sent


GONE_NOTETYPES = "muisti.goneNotetypes"
LOCAL_TABLES = ("notes", "cards", "revlog", "decks", "deck_config", "notetypes", "config")


def _apply(col, pulled: dict, first: bool = False) -> int:
    """Write what other devices changed into the local collection, without marking it as a local change.
    A local change not sent yet wins if it is newer, a local deletion not sent yet always wins.
    first: this device's first sync; whatever the account already has wins (a fresh collection's default
    preset, deck and settings must not overwrite the account's)."""
    def pending(sql):
        return dict(col.db.all(sql))

    gone = {(k, oid) for oid, k in col.db.all("select oid, type from graves where usn = -1")}
    local = {} if first else {
        "notes": pending("select id, mod from notes where usn = -1"),
        "cards": pending("select id, mod from cards where usn = -1"),
        "decks": pending("select id, mtime_secs from decks where usn = -1"),
        "deck_configs": pending("select id, mtime_secs from deck_config where usn = -1"),
        "notetypes": pending("select id, mtime_secs from notetypes where usn = -1"),
        "config": pending("select key, mtime_secs from config where usn = -1"),
    }
    kinds = {"cards": 0, "notes": 1, "decks": 2}

    def take(table):
        mine, kind = local.get(table, {}), kinds.get(table)
        for r in pulled[table]:
            key = r.get("key", r.get("id"))
            if (kind, key) in gone or mine.get(key, -1) > r["mod"]:
                continue
            yield r

    for r in take("config"):
        if r["key"] == "_crt":
            _adopt_crt(col, r["val"])
        elif r["deleted"]:
            col.db.execute("delete from config where key = ?", r["key"])
        else:
            col.set_config(r["key"], r["val"])  # the db proxy can't write blobs
            col.db.execute("update config set usn = 0, mtime_secs = ? where key = ?", r["mod"], r["key"])
    for r in take("deck_configs"):
        if not r["deleted"]:
            col._backend.add_or_update_deck_config_legacy(json.dumps({**r["data"], "usn": 0}).encode())
            # this call can't preserve usn/mtime: without this the preset would echo back as a local change
            col.db.execute("update deck_config set usn = 0, mtime_secs = ? where id = ?", r["mod"], r["id"])
    gone_decks = []
    for r in take("decks"):
        if r["deleted"]:
            gone_decks.append(r["id"])
        else:
            col._backend.add_or_update_deck_legacy(deck=json.dumps({**r["data"], "usn": 0}).encode(), preserve_usn_and_mtime=True)
    for r in take("notetypes"):
        if r["deleted"] and col.models.get(r["id"]):
            col.models.remove(r["id"])
    nts = [r for r in take("notetypes") if not r["deleted"]]
    twins = _park_twins(col, {r["data"]["name"]: r["id"] for r in nts})
    for r in nts:
        col._backend.add_or_update_notetype(json=json.dumps({**r["data"], "usn": 0}).encode(),
                                            preserve_usn_and_mtime=True, skip_checks=True)
    for i in twins:
        col.models.remove(i)
    # ponytail: deleted note types aren't synced (Anki itself needs a full sync for that); delete them on each device
    nids = []
    for r in take("notes"):
        if r["deleted"]:
            col.db.execute("delete from notes where id = ?", r["id"])
        else:
            col.db.execute(f"insert or replace into notes ({', '.join(NOTE_COLS)}, usn) values ({', '.join('?' * len(NOTE_COLS))}, 0)",
                           *[r[c] for c in NOTE_COLS])
            nids.append(r["id"])
    for r in take("cards"):
        if r["deleted"]:
            col.db.execute("delete from cards where id = ?", r["id"])
        else:
            col.db.execute(f"insert or replace into cards ({', '.join(CARD_COLS)}, usn) values ({', '.join('?' * len(CARD_COLS))}, 0)",
                           *[r[c] for c in CARD_COLS])
    for r in pulled["revlog"]:
        if r["deleted"]:  # an answer undone in the web app
            col.db.execute("delete from revlog where id = ?", r["id"])
            continue
        col.db.execute(f"insert or ignore into revlog ({', '.join(REVLOG_COLS)}, usn) values ({', '.join('?' * len(REVLOG_COLS))}, 0)",
                       *[r["last_ivl"] if c == "lastIvl" else r[c] for c in REVLOG_COLS])
    if nids:
        col.after_note_updates(nids, mark_modified=False, generate_cards=False)  # tags list, sort field, checksum
    if gone_decks:
        col.decks.remove(gone_decks)
        col.db.execute("delete from graves where usn = -1 and type = 2")  # deleted elsewhere, nothing to send
    return sum(len(rows) for rows in pulled.values())


def _park_twins(col, incoming: dict) -> list[int]:
    """Every new collection brings its own stock note types (other ids, same names). A local twin without notes
    is renamed out of the way and removed once the online one is in (removing first could leave no note type,
    and Anki would add a fresh "Basic"). Returns the ids to remove."""
    out = []
    for m in col.models.all_names_and_ids():
        if incoming.get(m.name, m.id) != m.id and not col.models.use_count(nt := col.models.get(m.id)):
            nt["name"] = f"{m.name} ~{m.id}"
            col.models.save(nt)
            out.append(m.id)
    return out


def _adopt_crt(col, crt: int):
    """Both sides must count due days from the same day 0. Shift local review cards when it differs."""
    shift = (col.crt - crt) // 86400
    if shift:
        col.db.execute("update cards set due = due + ? where type = 2 and queue in (2, 3, -2, -3)", shift)
        col.db.execute("update cards set odue = odue + ? where odid != 0 and type = 2", shift)
        col.crt = crt


def sync_media(col, account: Account) -> int:
    """Copy files that only one side has. Returns the number copied.
    ponytail: deletions and edits of an existing file name aren't synced, Anki's editor always writes new names."""
    import os

    token, uid = account.token(), account.load()["user_id"]
    remote, offset = set(), 0
    while True:
        page = _http("POST", "/storage/v1/object/list/media", {"prefix": uid, "limit": 1000, "offset": offset}, token)
        remote |= {f["name"] for f in page if f.get("id")}  # folders have no id
        if len(page) < 1000:
            break
        offset += 1000
    folder = Path(col.media.dir())
    local = {f for f in os.listdir(folder) if (folder / f).is_file() and not f.startswith(".")}
    for name in local - remote:
        _http("POST", f"/storage/v1/object/media/{uid}/{urllib.parse.quote(name)}", (folder / name).read_bytes(), token,
              {"Content-Type": "application/octet-stream", "x-upsert": "true"})
    for name in remote - local:
        (folder / name).write_bytes(_http("GET", f"/storage/v1/object/authenticated/media/{uid}/{urllib.parse.quote(name)}", token=token))
    return len(local ^ remote)


TABLES = ("config", "deck_configs", "decks", "notetypes", "notes", "cards", "revlog")


def sync(col, account: Account, pull: bool = True) -> dict:
    """Pull what other devices changed, then push the local changes. Returns {'sent': n, 'received': m}.
    pull=False only pushes (the web worker right after its own change, having pulled just before)."""
    if not pull:
        d = account.load()
        return {"sent": _push(col, account.token(), d["device"], crt=False), "received": 0}
    token = account.token()
    d = account.load()
    since = d.get("last_usn") or 0
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(len(TABLES) + 1) as pool:  # the schema check and one request per table, all at once
        state = pool.submit(_http, "GET", "/rest/v1/sync_state?select=usn,schema", token=token)
        pulled = dict(zip(TABLES, pool.map(lambda t: _pull(token, t, since, d["device"]), TABLES)))
        state = state.result()
    if state and state[0]["schema"] > SCHEMA:
        raise CloudError("Bitte aktualisiere Muisti, um mit deinem Konto zu synchronisieren.")
    first = d.get("last_usn") is None
    if first:  # everything here is new to the account; what the pull brings in is marked as synced
        for t in LOCAL_TABLES:
            col.db.execute(f"update {t} set usn = -1")
    received = _apply(col, pulled, first)
    sent = _push(col, token, d["device"], crt=first and not any(r["key"] == "_crt" for r in pulled["config"]))
    # not the newest usn online: another device may have written since, and our own rows are skipped anyway
    account.set(last_usn=max([since] + [r["usn"] for rows in pulled.values() for r in rows]))
    return {"sent": sent, "received": received}
