"""Thin facade over Anki's own backend. UI (pywebview js_api) and MCP both call these methods.

Every public method takes/returns plain JSON-able values.
"""

import functools
import html
import os
import re
import sys
import threading
from pathlib import Path

from anki.collection import (
    Collection,
    DeckIdLimit,
    ExportAnkiPackageOptions,
    ImportAnkiPackageOptions,
    ImportAnkiPackageRequest,
    ImportCsvRequest,
)
import anki.lang
from anki.sound import SoundOrVideoTag, TTSTag

# UI language (Settings) -> Anki's own strings: interval labels, undo names, import messages, stats
_ANKI_LANGS = {"de": "de_DE", "en": "en_US", "es": "es_ES"}
anki.lang.set_lang("de_DE")


def data_dir() -> Path:
    if os.environ.get("MUISTI_DIR"):  # separate profile, e.g. for testing
        base = Path(os.environ["MUISTI_DIR"])
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ["APPDATA"])
    else:
        base = Path.home() / ".local" / "share"
    d = base if os.environ.get("MUISTI_DIR") else base / "Muisti"
    legacy = base / "BetterAnki"  # ponytail: the app's name before 0.4.0; drop this move a few versions later
    if not os.environ.get("MUISTI_DIR") and not d.exists() and legacy.is_dir():
        legacy.rename(d)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _config_file() -> Path:
    return data_dir() / "config.json"


def load_config() -> dict:
    import json

    f = _config_file()
    return json.loads(f.read_text()) if f.exists() else {}


def save_config(**changes) -> None:
    import json

    _config_file().write_text(json.dumps({**load_config(), **changes}, indent=2))


def collection_dir() -> Path:
    """Where the collection (cards, media, backups) lives. Default: the app data folder; user-selectable."""
    d = Path(load_config().get("collection_dir") or data_dir())
    d.mkdir(parents=True, exist_ok=True)
    return d


def collection_path() -> str:
    return str(collection_dir() / "collection.anki2")


_SYNCED_FOLDERS = ("onedrive", "icloud", "mobile documents", "dropbox", "google drive", "cloudstorage", "nextcloud", "box sync")


def looks_synced(path: Path) -> bool:
    """Cloud-sync clients can corrupt an open SQLite database (Anki warns about the same)."""
    return any(part in str(path).lower() for part in _SYNCED_FOLDERS)


def _locked(fn):
    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        with self._lock:
            return fn(self, *a, **kw)

    return wrapper


def _strip(text: str) -> str:
    text = re.sub(r"<style.*?</style>|<script.*?</script>|\[sound:[^\]]+\]", "", text, flags=re.S)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"[\u2068\u2069]", "", text).strip()


_SPEAKER = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/>'
            '<path d="M19 5a10 10 0 0 1 0 14"/></svg>')


class Core:
    def __init__(self, path: str | None = None):
        self._col = Collection(path or collection_path())
        self._apply_language()
        self._lock = threading.RLock()  # ponytail: one lock for everything, the collection is single-user anyway
        self._window = None  # set by app.py for file dialogs
        self._current = None  # (card, states) of the card being studied
        self._typed = None  # (expected, combining) when the current card has {{type:Field}}

    def _close(self):
        self._col.close()

    # ---------- decks ----------

    @_locked
    def decks(self) -> list[dict]:
        def walk(node, prefix=""):
            name = f"{prefix}::{node.name}" if prefix else node.name
            return {
                "id": node.deck_id,
                "name": name,
                "short": node.name,
                "new": node.new_count,
                "learn": node.learn_count,
                "review": node.review_count,
                "collapsed": node.collapsed,
                "filtered": node.filtered,
                "children": [walk(c, name) for c in node.children],
            }

        root = self._col.sched.deck_due_tree()
        return [walk(c) for c in root.children]

    @_locked
    def create_deck(self, name: str) -> int:
        return self._col.decks.id(name.strip())

    @_locked
    def rename_deck(self, deck_id: int, name: str) -> None:
        self._col.decks.rename(deck_id, name.strip())

    @_locked
    def delete_deck(self, deck_id: int) -> None:
        self._col.decks.remove([deck_id])

    @_locked
    def set_collapsed(self, deck_id: int, collapsed: bool) -> None:
        self._col.decks.set_collapsed(deck_id, collapsed, scope=0)  # 0 = REVIEWER scope

    # ---------- deck options (presets) & FSRS ----------

    # every scalar option of an Anki preset is exposed; these are list-valued or internal
    _LIST_OPTIONS = ("learn_steps", "relearn_steps", "easy_days_percentages")
    _HIDDEN_OPTIONS = ("fsrs_params_4", "fsrs_params_5", "fsrs_params_6", "other")
    _LIMITS = ("new", "review", "new_today", "review_today")

    def _configs_for(self, deck_id: int):
        info = self._col.decks.get_deck_configs_for_update(deck_id)
        return info, {c.config.id: c for c in info.all_config}

    @_locked
    def deck_options(self, deck_id: int, preset_id: int | None = None) -> dict:
        """All of Anki's preset options (flat, by their protobuf names) plus deck-only limits and global flags."""
        info, by_id = self._configs_for(deck_id)
        cfg = by_id[preset_id or info.current_deck.config_id].config
        c = cfg.config
        opts = {}
        for f in c.DESCRIPTOR.fields:
            if f.name in self._HIDDEN_OPTIONS:
                continue
            v = getattr(c, f.name)
            opts[f.name] = [round(x, 4) for x in v] if f.name in self._LIST_OPTIONS else round(v, 4) if isinstance(v, float) else v
        lim = info.current_deck.limits
        return {
            **opts,
            "deck_name": info.current_deck.name,
            "preset_id": cfg.id,
            "presets": [{"id": x.config.id, "name": x.config.name, "decks": x.use_count} for x in info.all_config],
            "fsrs": info.fsrs,
            "fsrs_optimized": len(c.fsrs_params_6) > 0,
            "days_since_optimize": info.days_since_last_fsrs_optimize,
            # deck-only overrides; None = use the preset
            "limits": {k: (getattr(lim, k) if lim.HasField(k) else None) for k in self._LIMITS},
            "subdecks": len(self._col.decks.deck_and_child_ids(deck_id)) - 1,
            "new_cards_ignore_review_limit": info.new_cards_ignore_review_limit,
            "apply_all_parent_limits": info.apply_all_parent_limits,
        }

    def _save_configs(self, deck_id: int, info, cfg, fsrs: bool, limits=None, flags: dict | None = None, reschedule=False):
        from anki.deck_config_pb2 import UpdateDeckConfigsRequest

        flags = flags or {}
        self._col.decks.update_deck_configs(UpdateDeckConfigsRequest(
            target_deck_id=deck_id,
            configs=[cfg],  # the last config is the one applied to the target deck
            limits=limits or info.current_deck.limits,
            card_state_customizer=info.card_state_customizer,
            new_cards_ignore_review_limit=flags.get("new_cards_ignore_review_limit", info.new_cards_ignore_review_limit),
            apply_all_parent_limits=flags.get("apply_all_parent_limits", info.apply_all_parent_limits),
            fsrs=fsrs,
            fsrs_reschedule=reschedule,
            fsrs_health_check=info.fsrs_health_check,
        ))

    @_locked
    def save_deck_options(self, deck_id: int, options: dict) -> None:
        """options: same shape as deck_options(); unknown keys are ignored, missing keys keep their value.
        'fsrs_reschedule': True reschedules all cards when FSRS settings change."""
        info, by_id = self._configs_for(deck_id)
        cfg = by_id[options.get("preset_id", info.current_deck.config_id)].config
        c = cfg.config
        for f in c.DESCRIPTOR.fields:
            if f.name in self._HIDDEN_OPTIONS or f.name not in options:
                continue
            if f.name in self._LIST_OPTIONS:
                del getattr(c, f.name)[:]
                getattr(c, f.name).extend(float(x) for x in options[f.name])
            else:
                setattr(c, f.name, type(getattr(c, f.name))(options[f.name]))
        limits = None
        if "limits" in options:
            limits = type(info.current_deck.limits)()
            limits.CopyFrom(info.current_deck.limits)
            for k in self._LIMITS:
                v = options["limits"].get(k)
                limits.ClearField(k) if v in (None, "") else setattr(limits, k, int(v))
            limits.new_today_active = options["limits"].get("new_today") not in (None, "")
            limits.review_today_active = options["limits"].get("review_today") not in (None, "")
        self._save_configs(deck_id, info, cfg, bool(options.get("fsrs", info.fsrs)), limits,
                           {k: options[k] for k in ("new_cards_ignore_review_limit", "apply_all_parent_limits") if k in options},
                           bool(options.get("fsrs_reschedule")))
        if limits is not None and options.get("limits_to_subdecks"):  # the deck's own limits for its subdecks too
            for did in self._col.decks.deck_and_child_ids(deck_id)[1:]:
                d = self._col.decks.get(did)
                if d["dyn"]:
                    continue
                d["newLimit"] = limits.new if limits.HasField("new") else None
                d["reviewLimit"] = limits.review if limits.HasField("review") else None
                self._col.decks.save(d)

    _MIXED = "muisti.mixedSubdecks"

    @_locked
    def mix_subdecks_by_default(self) -> None:
        """Once per collection: presets on Anki's default "gather new cards by deck" (one subdeck after the other)
        switch to random notes, so studying a parent deck mixes its subdecks. Deck options can switch it back."""
        if self._col.get_config(self._MIXED, False):
            return
        for c in self._col.decks.all_config():
            if c.get("newGatherPriority", 0) == 0:
                c["newGatherPriority"] = 4
                self._col.decks.update_config(c)
        self._col.set_config(self._MIXED, True)

    # ---------- global preferences ----------

    @_locked
    def preferences(self) -> dict:
        from google.protobuf.json_format import MessageToDict

        p = MessageToDict(self._col.get_preferences(), preserving_proto_field_name=True, always_print_fields_with_no_presence=True)
        p["scheduling"].pop("new_review_mix", None)  # legacy, superseded by the per-preset option
        return p

    @_locked
    def save_preferences(self, prefs: dict) -> None:
        from google.protobuf.json_format import ParseDict

        p = self._col.get_preferences()
        ParseDict(prefs, p, ignore_unknown_fields=True)
        self._col.set_preferences(p)

    @_locked
    def new_preset(self, deck_id: int, name: str) -> int:
        """Clone the deck's current preset under a new name and assign it to the deck."""
        info, by_id = self._configs_for(deck_id)
        cfg = by_id[info.current_deck.config_id].config
        clone = type(cfg)()
        clone.CopyFrom(cfg)
        clone.id = 0  # 0 = create new
        clone.name = name.strip()
        self._save_configs(deck_id, info, clone, info.fsrs)
        return self._col.decks.get(deck_id)["conf"]

    @_locked
    def optimize_fsrs(self, deck_id: int) -> dict:
        """Fit FSRS parameters to this preset's review history (needs a few hundred reviews to matter)."""
        info, by_id = self._configs_for(deck_id)
        cfg = by_id[info.current_deck.config_id].config
        c = cfg.config
        search = c.param_search or f'preset:"{cfg.name}" -is:suspended'
        res = self._col._backend.compute_fsrs_params(
            search=search, current_params=list(c.fsrs_params_6), ignore_revlogs_before_ms=0,
            num_of_relearning_steps=len(c.relearn_steps), health_check=False,
        )
        changed = list(res.params) != list(c.fsrs_params_6) and len(res.params) > 0
        if changed:
            del c.fsrs_params_6[:]
            c.fsrs_params_6.extend(res.params)
            self._save_configs(deck_id, info, cfg, True)
        return {"reviews": res.fsrs_items, "changed": changed}

    # ---------- filtered decks ----------

    @_locked
    def create_filtered_deck(self, name: str, search: str, limit: int = 100, order: int = 1, reschedule: bool = True) -> int:
        """order: 0 zuletzt gesehen, 1 zufällig, 2 kleinstes Intervall, 3 größtes Intervall, 4 meiste Fehler,
        5 hinzugefügt, 6 fällig, 7 zuletzt hinzugefügt, 8 relativ überfällig."""
        did = self._col.decks.new_filtered(name.strip())
        d = self._col.decks.get(did)
        d["terms"] = [[search, int(limit), int(order)]]
        d["resched"] = bool(reschedule)
        self._col.decks.save(d)
        self._col.sched.rebuild_filtered_deck(did)
        return did

    @_locked
    def rebuild_filtered_deck(self, deck_id: int) -> int:
        return self._col.sched.rebuild_filtered_deck(deck_id).count

    @_locked
    def empty_filtered_deck(self, deck_id: int) -> None:
        self._col.sched.empty_filtered_deck(deck_id)

    # ---------- note types ----------

    @_locked
    def notetype(self, notetype_id: int) -> dict:
        m = self._col.models.get(notetype_id)
        return {
            "id": m["id"], "name": m["name"], "cloze": m["type"] == 1, "css": m["css"],
            "use_count": self._col.models.use_count(m),
            "fields": [{"ord": f["ord"], "name": f["name"]} for f in m["flds"]],
            "templates": [{"ord": t["ord"], "name": t["name"], "qfmt": t["qfmt"], "afmt": t["afmt"]} for t in m["tmpls"]],
        }

    def _apply_notetype(self, data: dict):
        """Build an updated notetype dict from UI data. Entries keep their 'ord' (None = new) so
        Anki maps renames/reorders/removals onto existing notes."""
        m = self._col.models.get(data["id"])
        old_f = {f["ord"]: f for f in m["flds"]}
        old_t = {t["ord"]: t for t in m["tmpls"]}
        flds = []
        for f in data["fields"]:
            fd = dict(old_f[f["ord"]]) if f.get("ord") is not None else self._col.models.new_field(f["name"])
            fd["name"] = f["name"].strip()
            flds.append(fd)
        renames = {old_f[f["ord"]]["name"]: f["name"].strip() for f in data["fields"]
                   if f.get("ord") is not None and old_f[f["ord"]]["name"] != f["name"].strip()}

        def rename_refs(text):  # what Anki does on save, so the preview matches: {{Old}}, {{#Old}}, {{text:Old}} ...
            for old, new in renames.items():
                text = re.sub(r"(\{\{[#/^]?(?:[^{}:]*:)*)" + re.escape(old) + r"\}\}", lambda m: m.group(1) + new + "}}", text)
            return text

        tmpls = []
        for t in data["templates"]:
            td = dict(old_t[t["ord"]]) if t.get("ord") is not None else self._col.models.new_template(t["name"])
            td.update(name=t["name"].strip(), qfmt=rename_refs(t["qfmt"]), afmt=rename_refs(t["afmt"]))
            tmpls.append(td)
        m.update(name=data["name"].strip(), css=data["css"], flds=flds, tmpls=tmpls)
        return m

    @_locked
    def save_notetype(self, data: dict) -> None:
        self._col.models.update_dict(self._apply_notetype(data))

    @_locked
    def add_notetype(self, base_id: int, name: str) -> int:
        m = self._col.models.copy(self._col.models.get(base_id), add=False)
        m["name"] = name.strip()
        self._col.models.add_dict(m)
        return self._col.models.by_name(m["name"])["id"]

    @_locked
    def delete_notetype(self, notetype_id: int) -> None:
        self._col.models.remove(notetype_id)
        from .cloud import GONE_NOTETYPES  # the next sync removes it on the other devices too

        self._col.set_config(GONE_NOTETYPES, [*self._col.get_config(GONE_NOTETYPES, []), notetype_id])

    @_locked
    def preview_template(self, data: dict, template_index: int) -> dict:
        """Render unsaved template edits with placeholder field contents.

        Anki's renderer resolves field names through the *stored* notetype, so references to
        renamed fields are mapped back to their stored name and unknown (new) fields become literals.
        """
        stored = self._col.models.get(data["id"])
        by_ord = {f["ord"]: f["name"] for f in stored["flds"]}
        current = {f["ord"]: f["name"].strip() for f in data["fields"] if f.get("ord") is not None}
        to_stored = {new: by_ord[o] for o, new in current.items()}
        special = {"FrontSide", "Tags", "Deck", "Subdeck", "Card", "Type", "CardFlag"}

        def fix(text):
            def ref(mo):
                prefix, name = mo.group(1), mo.group(2).strip()
                if name in to_stored:
                    return f"{prefix}{to_stored[name]}}}}}"
                if name in by_ord.values() or name in special:
                    return mo.group(0)
                return f"({name})" if prefix == "{{" else ""  # new field: show a placeholder, drop its sections
            return re.sub(r"(\{\{[#/^]?(?:[^{}:]*:)*)([^{}:#/^][^{}]*?)\}\}", ref, text)

        t = data["templates"][template_index]
        tmpl = dict(stored["tmpls"][t["ord"]]) if t.get("ord") is not None else self._col.models.new_template(t["name"])
        tmpl.update(qfmt=fix(t["qfmt"]), afmt=fix(t["afmt"]))
        m = {**stored, "css": data["css"]}
        note = self._col.new_note(stored)
        note.fields = [
            "{{c1::Beispiel}} für den Lückentext" if stored["type"] == 1 and i == 0 else f"({current.get(f['ord'], f['name'])})"
            for i, f in enumerate(stored["flds"])
        ]
        ord_ = 0 if stored["type"] == 1 else template_index
        card = note.ephemeral_card(ord_, custom_note_type=m, custom_template=tmpl, fill_empty=True)
        out = card.render_output()  # already rendered from the layout; reload would look up a stored card
        return {"question": out.question_text, "answer": out.answer_text, "css": out.css, "ord": ord_}

    # ---------- backups & AnkiWeb sync ----------

    def _backup_dir(self) -> Path:
        d = Path(self._col.path).parent / "backups"
        d.mkdir(exist_ok=True)
        return d

    @_locked
    def backup(self, force: bool = True) -> bool:
        """force=False only backs up if Anki's periodic interval has passed (used on app exit)."""
        return self._col.create_backup(backup_folder=str(self._backup_dir()), force=force, wait_for_completion=True)

    def backups(self) -> list[dict]:
        files = sorted(self._backup_dir().glob("*.colpkg"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [{"path": str(p), "name": p.name, "size_kb": p.stat().st_size // 1024, "mtime": p.stat().st_mtime} for p in files]

    def data_folder(self) -> str:
        return str(data_dir())

    def _replace_collection(self, colpkg: str):
        """Replace the whole collection with a .colpkg (import or backup restore). A backup is made first."""
        import shutil
        import tempfile

        from anki._backend import RustBackend

        # copy the source first: the safety backup below can get the same timestamped name as it
        src = Path(tempfile.mkdtemp()) / "import.colpkg"
        shutil.copy(colpkg, src)
        self._col.create_backup(backup_folder=str(self._backup_dir()), force=True, wait_for_completion=True)
        path = self._col.path
        media_folder, media_db = self._col.media.dir(), str(Path(path).with_suffix(".media.db2"))
        self._col.close(downgrade=False)
        try:
            RustBackend().import_collection_package(col_path=path, backup_path=str(src), media_folder=media_folder, media_db=media_db)
        finally:
            self._col = Collection(path)
            self._current = None
            shutil.rmtree(src.parent, ignore_errors=True)

    @_locked
    def restore_backup(self, path: str) -> None:
        self._replace_collection(path)

    _SYNC_FILE = "sync.json"

    def _sync_auth(self):
        import json
        from anki.sync_pb2 import SyncAuth

        f = data_dir() / self._SYNC_FILE
        if not f.exists():
            return None
        d = json.loads(f.read_text())
        return SyncAuth(hkey=d["hkey"], endpoint=d.get("endpoint") or None)

    def sync_account(self) -> str | None:
        import json

        f = data_dir() / self._SYNC_FILE
        return json.loads(f.read_text()).get("username") if f.exists() else None

    @_locked
    def sync_login(self, username: str, password: str) -> None:
        import json

        if self.cloud_account():
            raise ValueError("Bitte zuerst vom Muisti-Konto abmelden: beide Synchronisierungen zusammen bringen den Lernstand durcheinander.")

        auth = self._col.sync_login(username=username, password=password, endpoint=None)
        f = data_dir() / self._SYNC_FILE
        f.write_text(json.dumps({"hkey": auth.hkey, "endpoint": auth.endpoint, "username": username}))
        f.chmod(0o600)  # the hkey is a login token

    def sync_logout(self) -> None:
        (data_dir() / self._SYNC_FILE).unlink(missing_ok=True)

    @_locked
    def sync(self) -> dict:
        """Normal sync. Returns {'full_required': True} when AnkiWeb needs a one-way full sync first."""
        from anki.sync_pb2 import SyncCollectionResponse as R

        auth = self._sync_auth()
        if not auth:
            raise ValueError("Nicht bei AnkiWeb angemeldet")
        out = self._col.sync_collection(auth, sync_media=False)
        if out.new_endpoint:
            auth.endpoint = out.new_endpoint
        if out.required in (R.FULL_SYNC, R.FULL_DOWNLOAD, R.FULL_UPLOAD):
            self._pending_full = (auth, out.server_media_usn)
            return {"full_required": True, "direction": {R.FULL_DOWNLOAD: "download", R.FULL_UPLOAD: "upload"}.get(out.required),
                    "message": out.server_message}
        self._col.sync_media(auth)
        return {"full_required": False, "message": out.server_message}

    @_locked
    def full_sync(self, upload: bool) -> None:
        auth, media_usn = getattr(self, "_pending_full", (self._sync_auth(), None))
        self._col.close_for_full_sync()
        try:
            self._col.full_upload_or_download(auth=auth, server_usn=media_usn, upload=upload)
        finally:
            self._col.reopen(after_full_sync=True)
            self._current = None
        self._col.sync_media(auth)

    # ---------- Muisti account (sync with the web app) ----------

    def _cloud(self):
        from .cloud import Account

        return Account(data_dir())

    def cloud_account(self) -> str | None:
        d = self._cloud().load()
        return d and d["email"]

    def cloud_login(self, email: str, password: str) -> None:
        if self.sync_account():
            raise ValueError("Bitte zuerst von AnkiWeb abmelden: beide Synchronisierungen zusammen bringen den Lernstand durcheinander.")
        self._cloud().login(email.strip(), password)

    def cloud_register(self, email: str, password: str) -> bool:
        """True: signed in. False: Supabase sent a confirmation mail first, sign in afterwards."""
        if self.sync_account():
            raise ValueError("Bitte zuerst von AnkiWeb abmelden: beide Synchronisierungen zusammen bringen den Lernstand durcheinander.")
        return self._cloud().register(email.strip(), password)

    def cloud_logout(self) -> None:
        self._cloud().logout()

    @_locked
    def cloud_sync(self) -> dict:
        from . import cloud

        acc = self._cloud()
        if not acc.load():
            return {"sent": 0, "received": 0}
        out = cloud.sync(self._col, acc)
        out["media"] = cloud.sync_media(self._col, acc)
        if out["received"]:
            self._current = self._typed = None
        return out

    # ---------- studying ----------

    def _render(self, card, side: str, autoplay: bool = True) -> str:
        out = card.render_output(reload=side == "q")
        text = out.question_text if side == "q" else out.answer_text
        tags = out.question_av_tags if side == "q" else out.answer_av_tags

        def audio(m):
            tag = tags[int(m.group(2))] if int(m.group(2)) < len(tags) else None
            auto = autoplay and m.group(1) == side
            if isinstance(tag, SoundOrVideoTag):
                return f'<audio controls {"autoplay" if auto else ""} src="{html.escape(tag.filename)}"></audio>'
            if isinstance(tag, TTSTag):  # spoken by the system voice via speechSynthesis inside the card frame
                return (f'<button class="ba-tts" data-auto="{int(auto)}" data-lang="{html.escape(tag.lang.replace("_", "-"))}" '
                        f'data-text="{html.escape(tag.field_text)}" aria-label="Vorlesen">{_SPEAKER}</button>')
            return ""

        return re.sub(r"\[anki:play:(q|a):(\d+)\]", audio, text)

    @_locked
    def next_card(self, deck_id: int) -> dict | None:
        self._col.decks.select(deck_id)
        queued = self._col.sched.get_queued_cards()
        if not queued.cards:
            self._current = None
            return None
        qc = queued.cards[0]
        card = self._col.get_card(qc.card.id)
        card.start_timer()
        self._current = (card, qc.states)
        labels = self._col.sched.describe_next_states(qc.states)
        study = self._study_options(card)
        question, answer = self._type_answer(card, self._render(card, "q", study["autoplay"]), self._render(card, "a", study["autoplay"]))
        return {
            "card_id": card.id,
            "note_id": card.nid,
            "ord": card.ord,
            "question": question,
            "answer": answer,
            "type_answer": self._typed is not None,  # the UI swaps [[typeans]] in the answer for compare_answer()
            "css": card.render_output().css,
            "buttons": [_strip(x) for x in labels],  # interval labels for Again/Hard/Good/Easy
            "counts": {"new": queued.new_count, "learn": queued.learning_count, "review": queued.review_count},
            "queue": qc.queue,  # 0 new, 1 learning, 2 review
            "study": study,
        }

    _TYPE = re.compile(r"\[\[type:(.+?)\]\]")

    def _type_answer(self, card, question: str, answer: str) -> tuple[str, str]:
        """{{type:Field}}, {{type:cloze:Text}}, {{type:nc:Field}}: an input on the front, the comparison on the back (like Anki's reviewer)."""
        self._typed = None
        m = self._TYPE.search(question)
        if not m:
            return question, self._TYPE.sub("", answer)
        fld, cloze, combining = m.group(1), False, True
        if fld.startswith("cloze:"):
            cloze, fld = True, fld.split(":", 1)[1]
        if fld.startswith("nc:"):
            combining, fld = False, fld.split(":", 1)[1]
        note = card.note()
        if fld not in note:
            return self._TYPE.sub(f"<p>Feld „{html.escape(fld)}“ zum Eintippen gibt es nicht.</p>", question), self._TYPE.sub("", answer)
        expected = self._col.extract_cloze_for_typing(note[fld], card.ord + 1) if cloze else note[fld]
        self._typed = (expected, combining)
        field = '<input id="typeans" type="text" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false">'
        return self._TYPE.sub(field, question, count=1), self._TYPE.sub("[[typeans]]", answer, count=1)

    @_locked
    def compare_answer(self, card_id: int, typed: str) -> str:
        """Anki's diff of the typed answer against the field (HTML)."""
        card = self._current[0] if self._current else None
        if not card or card.id != card_id or not self._typed:
            raise ValueError("card is no longer current")
        expected, combining = self._typed
        return self._col.compare_answer(expected, typed, combining)  # <code id=typeans>…</code>

    @_locked
    def leave_study(self) -> None:
        """The study screen was closed: nothing is current for current_card() anymore."""
        self._current = self._typed = None

    @_locked
    def current_card(self) -> dict | None:
        """The card on the study screen right now (for Claude: 'explain this', 'improve this card')."""
        if not self._current:
            return None
        card = self._current[0]
        note = card.note()
        out = card.render_output()
        return {
            "card_id": card.id, "note_id": note.id, "notetype": note.note_type()["name"],
            "deck": self._col.decks.name(card.odid or card.did), "fields": dict(note.items()), "tags": note.tags,
            "question": _strip(out.question_text), "answer": _strip(out.answer_text),
            "lapses": card.lapses, "reviews": card.reps, "interval_days": card.ivl,
        }

    def _study_options(self, card) -> dict:
        """The preset options the review screen itself has to honour (audio, timer, auto advance)."""
        conf = self._col.decks.config_dict_for_deck_id(card.current_deck_id())
        return {
            "autoplay": conf.get("autoplay", True),
            "show_timer": bool(conf.get("timer", 0)),
            "stop_timer_on_answer": conf.get("stopTimerOnAnswer", False),
            "cap_secs": conf.get("maxTaken", 60),
            "seconds_question": conf.get("secondsToShowQuestion", 0),
            "seconds_answer": conf.get("secondsToShowAnswer", 0),
            "question_action": conf.get("questionAction", 0),  # 0 show answer, 1 show reminder
            "answer_action": conf.get("answerAction", 0),  # 0 bury, 1 again, 2 good, 3 hard, 4 reminder
            "wait_for_audio": conf.get("waitForAudio", True),
        }

    @_locked
    def answer(self, card_id: int, ease: int) -> None:
        card, states = self._current or (None, None)
        if not card or card.id != card_id:
            raise ValueError("card is no longer current")
        answer = self._col.sched.build_answer(card=card, states=states, rating=ease - 1)
        self._col.sched.answer_card(answer)
        self._current = None

    @_locked
    def undo(self) -> str | None:
        name = self._col.undo_status().undo
        if name:
            self._col.undo()
        return name or None

    @_locked
    def bury_card(self, card_id: int) -> None:
        self._col.sched.bury_cards([card_id])

    # ---------- learn ahead from the timeline ----------

    _PRELEARN = "Vorlernen"
    _TEMP = ("Vorlernen", "Üben:")  # temporary filtered decks, removed when their session ends

    def _temp_deck(self, name: str, search: str, order: int = 6) -> int:
        """A filtered deck for one session; previous ones of any temporary kind are removed first."""
        for d in self._col.decks.all_names_and_ids():
            if d.name.startswith(self._TEMP) and self._col.decks.is_filtered(d.id):
                self._col.decks.remove([d.id])
        did = self._col.decks.new_filtered(name)
        d = self._col.decks.get(did)
        d["terms"] = [[search, 9999, order]]
        d["resched"] = True
        self._col.decks.save(d)
        if not self._col.sched.rebuild_filtered_deck(did).count:
            self._col.decks.remove([did])
            return 0
        return did

    @_locked
    def prelearn(self, days_ahead: int) -> dict:
        """Gather the cards due in `days_ahead` days into a temporary filtered deck and reschedule them on answer
        (Anki's 'review ahead'). Any previous pre-learn deck is emptied first."""
        import datetime

        if days_ahead < 1:
            raise ValueError("Nur Tage in der Zukunft lassen sich vorlernen.")
        when = datetime.date.today() + datetime.timedelta(days=days_ahead)
        name = f"{self._PRELEARN} {when.strftime('%d.%m.')}"
        did = self._temp_deck(name, f"prop:due={days_ahead}", 6)  # 6 = order due
        if not did:
            raise ValueError(f"Am {when.strftime('%d.%m.')} ist nichts fällig.")
        return {"deck_id": did, "name": name, "count": len(self._col.decks.cids(did))}

    @_locked
    def end_prelearn(self, deck_id: int) -> None:
        """Remove the temporary deck; unanswered cards go back to their home decks unchanged."""
        if self._col.decks.is_filtered(deck_id) and self._col.decks.name(deck_id).startswith(self._TEMP):
            self._col.decks.remove([deck_id])

    # ---------- optional features (stored in the collection, so they travel with backups and sync) ----------
    # keys keep the old "betteranki." prefix: renaming them would drop settings and exam dates from existing collections

    _FEATURES = {"exams": False, "plan": False, "weak": False, "inbox": True}

    @_locked
    def features(self) -> dict:
        return {**self._FEATURES, **self._col.get_config("betteranki.features", {})}

    @_locked
    def theme(self) -> str:
        return self._col.get_config("betteranki.theme", "system")

    @_locked
    def set_theme(self, theme: str) -> None:
        if theme not in ("system", "light", "dark"):
            raise ValueError(theme)
        self._col.set_config("betteranki.theme", theme)

    @_locked
    def language(self) -> str | None:
        return self._col.get_config("betteranki.lang", None)

    @_locked
    def set_language(self, lang: str) -> None:
        if lang not in _ANKI_LANGS:
            raise ValueError(lang)
        self._col.set_config("betteranki.lang", lang)
        self._apply_language()

    def _apply_language(self):
        # Anki fixes its language when a collection is opened: reopen if it changed
        # ponytail: set_lang is process-wide but only read on open, so each web worker collection keeps its own
        want = _ANKI_LANGS.get(self._col.get_config("betteranki.lang", "de"), "de_DE")
        if want != anki.lang.current_lang:
            anki.lang.set_lang(want)
            path = self._col.path
            self._col.close()
            self._col = Collection(path)
            self._current = None

    @_locked
    def save_features(self, features: dict) -> None:
        self._col.set_config("betteranki.features", {k: bool(features[k]) for k in self._FEATURES if k in features})

    # ---------- 1. exam dates ----------

    def _exams(self) -> dict:
        return self._col.get_config("betteranki.exams", {})  # {deck_id: "YYYY-MM-DD"}

    @_locked
    def set_exam(self, deck_id: int, date: str | None) -> None:
        exams = self._exams()
        if date:
            exams[str(deck_id)] = date
        else:
            exams.pop(str(deck_id), None)
        self._col.set_config("betteranki.exams", exams)

    @_locked
    def exam_plan(self) -> list[dict]:
        """Per exam: how many new cards a day finish the deck in time, leaving the last days for reviews only."""
        import datetime
        import math

        today = datetime.date.today()
        out = []
        for did, date in sorted(self._exams().items(), key=lambda kv: kv[1]):
            if not self._col.decks.get(int(did), default=False):
                continue  # deck was deleted
            days = (datetime.date.fromisoformat(date) - today).days
            ids = ",".join(map(str, self._col.decks.deck_and_child_ids(int(did))))
            new_left = self._col.db.scalar(f"select count() from cards where queue = 0 and did in ({ids})")
            # ponytail: fixed rule, last fifth of the time (1–7 days) is for reviewing what was learned
            buffer = min(7, max(1, days // 5))
            per_day = math.ceil(new_left / max(1, days - buffer)) if new_left and days > 0 else 0
            info = self._col.decks.get_deck_configs_for_update(int(did))
            lim = info.current_deck.limits
            current = lim.new if lim.HasField("new") else self._col.decks.config_dict_for_deck_id(int(did))["new"]["perDay"]
            out.append({"deck_id": int(did), "name": self._col.decks.name(int(did)), "date": date, "days": days,
                        "new_left": new_left, "per_day": per_day, "current": current, "buffer": buffer})
        return out

    @_locked
    def apply_exam_pace(self, deck_id: int) -> int:
        """Set this deck's own new-cards limit (not the shared preset) to the pace its exam needs."""
        plan = next(p for p in self.exam_plan() if p["deck_id"] == deck_id)
        info, by_id = self._configs_for(deck_id)
        limits = type(info.current_deck.limits)()
        limits.CopyFrom(info.current_deck.limits)
        limits.new = plan["per_day"]
        self._save_configs(deck_id, info, by_id[info.current_deck.config_id].config, info.fsrs, limits)
        return plan["per_day"]

    # ---------- 2. study plan across decks ----------

    @_locked
    def plan_next(self) -> dict | None:
        """Next card of a session across all decks: decks with the nearest exam first, then the rest in order."""
        exams = self._exams() if self.features()["exams"] else {}
        tops = [d for d in self.decks() if not d["filtered"]]
        tops.sort(key=lambda d: min((exams[str(i)] for i in self._col.decks.deck_and_child_ids(d["id"]) if str(i) in exams), default="9999"))
        for d in tops:
            if d["new"] + d["learn"] + d["review"] and (card := self.next_card(d["id"])):
                return {**card, "deck": d["name"]}
        return None

    # ---------- 3. weak spots ----------

    @_locked
    def weak_spots(self, days: int = 90, min_reviews: int = 10) -> dict:
        """Retention of review answers per tag and per deck, weakest first."""
        names = {d.id: d.name for d in self._col.decks.all_names_and_ids()}
        rows = self._col.db.all(
            "select n.tags, (case when c.odid then c.odid else c.did end), r.ease > 1 from revlog r "
            "join cards c on c.id = r.cid join notes n on n.id = c.nid where r.id > ? and r.type = 1",
            (self._col.sched.day_cutoff - days * 86400) * 1000,
        )
        groups = {}
        for tags, did, ok in rows:
            name = names.get(did, "?")
            keys = [("tag", t) for t in tags.split() if t != self._INBOX_TAG]
            keys += [("deck", "::".join(name.split("::")[:i + 1])) for i in range(name.count("::") + 1)]
            for k in keys:
                g = groups.setdefault(k, [0, 0])
                g[0] += ok
                g[1] += 1
        total = len(rows)
        overall = round(100 * sum(r[2] for r in rows) / total) if total else None
        spots, seen = [], set()
        for (k, n), (p, t) in sorted(groups.items(), key=lambda kv: kv[0][0] != "deck"):  # decks first
            if t >= min_reviews and 100 * p / t < (overall or 0) and (p, t) not in seen:  # a tag covering exactly a deck once
                seen.add((p, t))
                spots.append({"kind": k, "name": n, "reviews": t, "retention": round(100 * p / t)})
        spots.sort(key=lambda x: (x["retention"], -x["reviews"]))
        return {"overall": overall, "reviews": total, "spots": spots[:10]}

    @_locked
    def practice(self, kind: str, name: str) -> dict:
        """Temporary deck with the cards of a tag/deck that were forgotten lately or often."""
        scope = f'"tag:{name}"' if kind == "tag" else f'"deck:{name}"'
        title = f"Üben: {name.split('::')[-1]}"
        did = self._temp_deck(title, f"{scope} -is:suspended -is:new (rated:90:1 OR prop:lapses>=2)", 4)  # 4 = most lapses
        if not did:
            raise ValueError("Keine vergessenen Karten zum Üben gefunden.")
        return {"deck_id": did, "name": title, "count": len(self._col.decks.cids(did))}

    # ---------- 4. inbox for cards made by Claude ----------

    _INBOX_TAG = "Claude-Eingang"

    @_locked
    def inbox(self) -> list[dict]:
        out = []
        for nid in self._col.find_notes(f"tag:{self._INBOX_TAG}"):
            note = self._col.get_note(nid)
            cards = note.cards()
            out.append({
                "note_id": nid,
                "notetype": note.note_type()["name"],
                "deck": self._col.decks.name(cards[0].did) if cards else "?",
                "fields": [[k, _strip(v)[:400]] for k, v in note.items()],
                "tags": [t for t in note.tags if t != self._INBOX_TAG],
                "cards": len(cards),
            })
        return out

    @_locked
    def inbox_count(self) -> int:
        return len(self._col.find_notes(f"tag:{self._INBOX_TAG}"))

    @_locked
    def accept_inbox(self, note_ids: list[int]) -> int:
        """Into normal study: unsuspend and drop the inbox tag."""
        cids = [c for nid in note_ids for c in self._col.card_ids_of_note(nid)]
        self._col.sched.unsuspend_cards(cids)
        self._col.tags.bulk_remove(note_ids, self._INBOX_TAG)
        return len(note_ids)

    @_locked
    def reject_inbox(self, note_ids: list[int]) -> int:
        return self._col.remove_notes(note_ids).count

    # ---------- 5. for Claude: cards that keep being forgotten ----------

    @_locked
    def difficult_cards(self, deck: str | None = None, limit: int = 20) -> list[dict]:
        """Cards forgotten at least twice (or tagged leech), most lapses first, with full fields."""
        query = "(prop:lapses>=2 OR tag:leech)" + (f' "deck:{deck}"' if deck else "")
        out = []
        for cid in self._col.find_cards(query, order="c.lapses desc")[:limit]:
            card = self._col.get_card(cid)
            note = card.note()
            out.append({
                "card_id": cid, "note_id": note.id, "notetype": note.note_type()["name"],
                "deck": self._col.decks.name(card.odid or card.did), "fields": dict(note.items()), "tags": note.tags,
                "lapses": card.lapses, "reviews": card.reps, "interval_days": card.ivl,
            })
        return out

    # ---------- notes ----------

    @_locked
    def note_types(self) -> list[dict]:
        if not any(m.get("originalStockKind") == 6 for m in self._col.models.all()):
            self._col.add_image_occlusion_notetype()  # Anki's own type; its fields are Occlusion, Image, Header, Back Extra, Comments
        return [
            {"id": m["id"], "name": m["name"], "fields": [f["name"] for f in m["flds"]], "cloze": m["type"] == 1,
             "basic": m.get("originalStockKind") == 1, "io": m.get("originalStockKind") == 6}
            for m in self._col.models.all()
        ]

    def _notetype(self, notetype):
        m = self._col.models.by_name(notetype) if isinstance(notetype, str) else self._col.models.get(notetype)
        if not m and notetype in ("Basic", "Cloze"):  # stock names differ per language ("Einfach", "Lückentext")
            kind = 5 if notetype == "Cloze" else 1  # originalStockKind
            m = next((x for x in self._col.models.all() if x.get("originalStockKind") == kind), None)
        if not m:
            raise ValueError(f"unknown note type: {notetype}")
        return m

    def _fill(self, note, fields):
        names = list(note.keys())
        if isinstance(fields, list):
            fields = dict(zip(names, fields))
        aliases = {"Front": 0, "Text": 0, "Back": 1, "Back Extra": 1}  # English stock names on a German collection
        for k, v in fields.items():
            if k not in names and aliases.get(k, 99) < len(names):
                k = names[aliases[k]]
            if k not in names:
                raise ValueError(f"unknown field '{k}', expected one of {names}")
            note[k] = v

    def _duplicate_of(self, note) -> int | None:
        """Another note of the same type with the same first field (Anki's dupe check, HTML ignored)."""
        from anki.collection import SearchNode

        if not _strip(note.fields[0]):
            return None
        node = SearchNode(dupe=SearchNode.Dupe(notetype_id=note.mid, first_field=note.fields[0]))
        return next((i for i in self._col.find_notes(self._col.build_search_string(node)) if i != note.id), None)

    @_locked
    def duplicate_of(self, notetype, first_field: str, note_id: int | None = None) -> int | None:
        note = self._col.get_note(note_id) if note_id else self._col.new_note(self._notetype(notetype))
        note.fields[0] = first_field
        return self._duplicate_of(note)

    @_locked
    def add_note(self, notetype, deck, fields, tags: list[str] | None = None, inbox: bool = False, allow_duplicate: bool = True) -> int:
        """notetype/deck: name or id. fields: {name: value} or list in field order.
        inbox: a card made by Claude; waits suspended in the inbox for review if that feature is on."""
        note = self._col.new_note(self._notetype(notetype))
        self._fill(note, fields)
        if not allow_duplicate and (dup := self._duplicate_of(note)):
            raise ValueError(f"duplicate of note {dup} (same first field); update that note instead, or pass allow_duplicate")
        inbox = inbox and self.features()["inbox"]
        note.tags = (tags or []) + ([self._INBOX_TAG] if inbox else [])
        deck_id = deck if isinstance(deck, int) else self._col.decks.id(deck)
        if not note.fields[0].strip():
            raise ValueError("first field must not be empty")
        self._col.add_note(note, deck_id)
        if inbox:
            self._col.sched.suspend_cards(note.card_ids())
        return note.id

    @_locked
    def get_note(self, note_id: int) -> dict:
        note = self._col.get_note(note_id)
        cards = note.cards()
        return {
            "id": note.id,
            "notetype": note.note_type()["name"],
            "notetype_id": note.mid,
            "fields": dict(note.items()),
            "tags": note.tags,
            "deck_id": cards[0].did if cards else None,
            "card_ids": [c.id for c in cards],
        }

    @_locked
    def update_note(self, note_id: int, fields: dict | None = None, tags: list[str] | None = None, deck=None) -> None:
        note = self._col.get_note(note_id)
        if fields:
            self._fill(note, fields)
        accepted = tags is not None and self._INBOX_TAG in note.tags and self._INBOX_TAG not in tags
        if tags is not None:
            note.tags = tags
        self._col.update_note(note)
        if accepted:  # removing the inbox tag by hand counts as accepting the note
            self._col.sched.unsuspend_cards(note.card_ids())
        if deck is not None:
            deck_id = deck if isinstance(deck, int) else self._col.decks.id(deck)
            self._col.set_deck(note.card_ids(), deck_id)

    @_locked
    def delete_notes(self, note_ids: list[int]) -> int:
        return self._col.remove_notes(note_ids).count

    @_locked
    def add_media(self, filename: str, data_b64: str) -> str:
        """Store a pasted/dropped file in the media folder; returns the (possibly renamed) file name."""
        import base64

        return self._col.media.write_data(Path(filename).name or "bild.png", base64.b64decode(data_b64))

    # ---------- browser ----------

    @_locked
    def search(self, query: str = "", limit: int = 500) -> list[dict]:
        """Anki search syntax, e.g. 'deck:Spanish tag:verb is:due'. Returns one row per card."""
        rows = []
        decks = {d.id: d.name for d in self._col.decks.all_names_and_ids()}
        for cid in self._col.find_cards(query, order=True)[:limit]:
            card = self._col.get_card(cid)
            note = card.note()
            sortf = note.note_type()["sortf"]
            rows.append({
                "card_id": cid,
                "note_id": note.id,
                "sort": _strip(note.fields[sortf])[:200],
                "notetype": note.note_type()["name"],
                "deck": decks.get(card.odid or card.did, "?"),
                "tags": note.tags,
                "due": card.due if card.queue == 0 else None,
                "interval": card.ivl,
                "reps": card.reps,
                "suspended": card.queue == -1,
                "flag": card.user_flag(),
            })
        return rows

    @_locked
    def suspend(self, card_ids: list[int], suspended: bool = True) -> None:
        (self._col.sched.suspend_cards if suspended else self._col.sched.unsuspend_cards)(card_ids)

    @_locked
    def suspend_note(self, note_id: int) -> None:
        self._col.sched.suspend_notes([note_id])

    @_locked
    def flag(self, card_ids: list[int], flag: int) -> None:
        self._col.set_user_flag_for_cards(flag, card_ids)

    @_locked
    def forget_cards(self, card_ids: list[int]) -> int:
        """Anki's 'Forget': back to new, original position and review/lapse counts reset. Undoable."""
        self._col.sched.schedule_cards_as_new(card_ids, restore_position=True, reset_counts=True)
        return len(card_ids)

    @_locked
    def reset_deck(self, deck_id: int) -> int:
        """Reset the study progress of a deck and its subdecks, including today's new/review counters,
        otherwise the reset cards stay hidden behind today's already used daily limit."""
        undo = self._col.add_custom_undo_entry("Lernstand zurücksetzen")  # one undo step for both
        n = self.forget_cards(self._col.decks.cids(deck_id, children=True))
        for did in [deck_id, *(i for _, i in self._col.decks.children(deck_id))]:
            d = self._col.decks.get(did)
            d["newToday"] = d["revToday"] = [self._col.sched.today, 0]
            self._col.decks.save(d)
        self._col.merge_undo_entries(undo)
        return n

    @_locked
    def move_cards(self, card_ids: list[int], deck) -> None:
        deck_id = deck if isinstance(deck, int) else self._col.decks.id(deck)
        self._col.set_deck(card_ids, deck_id)

    @_locked
    def card_info(self, card_id: int) -> str:
        return self._col.card_stats(card_id, include_revlog=True)

    # ---------- stats ----------

    @_locked
    def stats(self) -> dict:
        return {
            "cards": self._col.card_count(),
            "notes": self._col.note_count(),
            "studied_today": _strip(self._col.studied_today()),
            "due_today": sum(d["new"] + d["learn"] + d["review"] for d in self.decks()),
        }

    @_locked
    def overview(self, past_days: int = 126, future_days: int = 28) -> dict:
        """Data for the 'Heute' screen: reviews per past day, forecast per future day, streak, retention."""
        db, sched = self._col.db, self._col.sched
        cutoff = sched.day_cutoff  # unix seconds of the next day rollover
        today = sched.today
        past = dict(db.all(
            "select (? - id/1000 - 1) / 86400 as ago, count() from revlog where id > ? group by ago",
            cutoff, (cutoff - past_days * 86400) * 1000,
        ))
        future = dict(db.all(
            "select due - ?, count() from cards where queue in (2,3) and due between ? and ? group by due",
            today, today, today + future_days,
        ))
        streak = 0
        while past.get(streak + (0 if past.get(0) else 1)):
            streak += 1
        month_ago = (cutoff - 30 * 86400) * 1000
        passed, total, secs = db.first(
            "select sum(ease > 1), count(), sum(time) / 1000.0 from revlog where id > ? and type = 1", month_ago
        ) or (0, 0, 0)
        avg_secs = (db.scalar("select avg(time) / 1000.0 from revlog where id > ?", month_ago) or 10)
        due = sum(d["new"] + d["learn"] + d["review"] for d in self.decks())
        return {
            "due": due,
            "minutes": round(due * avg_secs / 60),
            "streak": streak,
            "retention": round(100 * passed / total) if total else None,
            "past": [past.get(i, 0) for i in range(past_days - 1, -1, -1)],  # oldest first, last = today
            "future": [future.get(i, 0) for i in range(1, future_days + 1)],
            "overdue": {d["id"]: n for d in self._flat_decks() if (n := self._overdue(d["id"]))},
            "features": (features := self.features()),
            "exams": self.exam_plan() if features["exams"] else [],
            "inbox": self.inbox_count(),
        }

    def _flat_decks(self):
        def walk(nodes):
            for n in nodes:
                yield n
                yield from walk(n["children"])
        return list(walk(self.decks()))

    def _overdue(self, deck_id: int) -> int:
        ids = self._col.decks.deck_and_child_ids(deck_id)
        return self._col.db.scalar(
            f"select count() from cards where queue = 2 and due < ? and did in ({','.join(map(str, ids))})",
            self._col.sched.today,
        )

    @_locked
    def statistics(self, deck_id: int | None = None, days: int = 30) -> dict:
        """Chart data from Anki's own graph engine, flattened for the UI."""
        from google.protobuf.json_format import MessageToDict

        search = f'"deck:{self._col.decks.name(deck_id)}"' if deck_id else ""
        g = MessageToDict(self._col._backend.graphs(search=search, days=days))
        period = {30: "oneMonth", 90: "threeMonths"}.get(days, "oneYear")

        today = g.get("today", {})
        answered = today.get("answerCount", 0)

        future = [0] * days
        for k, n in g.get("futureDue", {}).get("futureDue", {}).items():
            if int(k) < days:
                future[max(0, int(k))] += n  # overdue lands on today

        reviews = [{"learn": 0, "relearn": 0, "young": 0, "mature": 0, "filtered": 0} for _ in range(days)]
        for k, v in g.get("reviews", {}).get("count", {}).items():
            if -days < int(k) <= 0:
                reviews[days - 1 + int(k)].update(v)

        buckets = [(1, 1, "1 T"), (2, 2, "2 T"), (3, 3, "3 T"), (4, 7, "4–7 T"), (8, 14, "1–2 W"), (15, 30, "2–4 W"),
                   (31, 90, "1–3 M"), (91, 180, "3–6 M"), (181, 365, "6–12 M"), (366, 10**9, "> 1 J")]
        ivls = {int(k): v for k, v in g.get("intervals", {}).get("intervals", {}).items()}
        intervals = [{"label": lab, "n": sum(v for i, v in ivls.items() if lo <= i <= hi)} for lo, hi, lab in buckets]

        retention = {}
        for k, v in g.get("trueRetention", {}).items():
            passed = v.get("youngPassed", 0) + v.get("maturePassed", 0)
            total = passed + v.get("youngFailed", 0) + v.get("matureFailed", 0)
            retention[k] = {"pct": round(100 * passed / total, 1) if total else None, "total": total}

        cc = g.get("cardCounts", {}).get("includingInactive", {})
        return {
            "today": {
                "answered": answered,
                "minutes": round(today.get("answerMillis", 0) / 60000, 1),
                "correct_pct": round(100 * today.get("correctCount", 0) / answered) if answered else None,
                "learn": today.get("learnCount", 0), "review": today.get("reviewCount", 0),
                "relearn": today.get("relearnCount", 0),
            },
            "future": future,
            "reviews": reviews,
            "intervals": intervals,
            "card_counts": {k: cc.get(src, 0) for k, src in [("new", "newCards"), ("learn", "learn"), ("relearn", "relearn"),
                            ("young", "young"), ("mature", "mature"), ("suspended", "suspended"), ("buried", "buried")]},
            "hours": [{"total": h.get("total", 0), "correct": h.get("correct", 0)} for h in g.get("hours", {}).get(period, [])],
            "buttons": {k: v for k, v in g.get("buttons", {}).get(period, {}).items()},
            "retention": retention,
        }

    # ---------- import / export ----------

    @_locked
    def inspect_import(self, path: str) -> dict:
        """What the import dialog needs to know before importing."""
        ext = Path(path).suffix.lower()
        info = {"path": path, "name": Path(path).name, "kind": {".apkg": "apkg", ".colpkg": "colpkg"}.get(ext, "csv")}
        if ext not in (".apkg", ".colpkg", ".csv", ".txt", ".tsv"):
            raise ValueError(f"„{Path(path).name}“ kann nicht importiert werden. Unterstützt: .apkg, .colpkg, .csv, .txt, .tsv")
        if info["kind"] == "csv":
            meta = self._col.get_csv_metadata(path, None)
            rows = [list(r.vals) for r in meta.preview][:6]
            info.update(
                columns=max((len(r) for r in rows), default=0),
                preview=rows,
                notetype_id=meta.global_notetype.id,
                field_columns=list(meta.global_notetype.field_columns),
                tags_column=meta.tags_column,
            )
        return info

    @_locked
    def import_file(self, path: str, deck=None, notetype_id: int | None = None,
                    field_columns: list[int] | None = None, tags_column: int | None = None) -> str:
        """CSV options: deck (name or id), notetype_id, field_columns (1-based column per field, 0 = empty), tags_column."""
        ext = Path(path).suffix.lower()
        if ext == ".apkg":
            req = ImportAnkiPackageRequest(
                package_path=path,
                options=ImportAnkiPackageOptions(with_scheduling=True, with_deck_configs=True),
            )
            log = self._col.import_anki_package(req).log
        elif ext == ".colpkg":
            self._replace_collection(path)
            return "Sammlung ersetzt (vorherige als Sicherung behalten)"
        elif ext in (".csv", ".txt", ".tsv"):
            meta = self._col.get_csv_metadata(path, None)
            if deck is not None:
                meta.deck_id = deck if isinstance(deck, int) else self._col.decks.id(deck)
            if notetype_id:
                meta.global_notetype.id = notetype_id
                if field_columns is None:  # columns in order onto the new type's fields
                    field_columns = [i + 1 for i in range(len(self._col.models.get(notetype_id)["flds"]))]
            if field_columns is not None:
                del meta.global_notetype.field_columns[:]
                meta.global_notetype.field_columns.extend(field_columns)
            if tags_column is not None:
                meta.tags_column = tags_column
            log = self._col.import_csv(ImportCsvRequest(path=path, metadata=meta)).log
        else:
            raise ValueError("unterstützt: .apkg, .colpkg, .csv, .txt, .tsv")
        return f"{len(log.new)} neu, {len(log.updated)} aktualisiert, {len(log.duplicate)} Duplikate"

    @_locked
    def export_deck(self, path: str, deck_id: int | None = None, scheduling: bool = True, media: bool = True) -> int:
        return self._col.export_anki_package(
            out_path=path,
            options=ExportAnkiPackageOptions(with_scheduling=scheduling, with_deck_configs=scheduling, with_media=media, legacy=False),
            limit=DeckIdLimit(deck_id) if deck_id else None,
        )

    @_locked
    def export_collection(self, path: str, media: bool = True) -> None:
        """Whole collection as .colpkg (for moving to another computer or Anki itself)."""
        try:
            self._col.export_collection_package(path, include_media=media, legacy=False)
        finally:
            self._col.reopen()  # Anki closes the collection for this export and leaves reopening to the caller
            self._current = None

    # ---------- migration from Anki desktop ----------

    @staticmethod
    def _anki_base() -> Path:
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "Anki2"
        if sys.platform == "win32":
            return Path(os.environ["APPDATA"]) / "Anki2"
        return Path.home() / ".local" / "share" / "Anki2"

    def anki_profiles(self) -> list[dict]:
        """Anki desktop profiles on this computer, read without opening them in Anki's sense (read-only SQLite)."""
        import sqlite3

        base = self._anki_base()
        out = []
        for col in sorted(base.glob("*/collection.anki2")) if base.exists() else []:
            info = {"name": col.parent.name, "path": str(col), "locked": False, "cards": None, "notes": None,
                    "modified": col.stat().st_mtime}
            try:
                db = sqlite3.connect(f"file:{col}?mode=ro", uri=True, timeout=0.3)
                info["cards"], info["notes"] = db.execute("select (select count() from cards), (select count() from notes)").fetchone()
                db.close()
            except sqlite3.OperationalError:
                info["locked"] = True  # Anki has it open (exclusive lock)
            media = col.parent / "collection.media"
            info["media"] = sum(1 for _ in os.scandir(media)) if media.exists() else 0
            out.append(info)
        return out

    @_locked
    def migrate_from_anki(self, collection: str, mode: str = "replace") -> str:
        """mode 'replace': this collection becomes a copy of Anki's (a backup is made first).
        mode 'merge': Anki's decks, cards, review history and media are imported into this collection.
        Anki's own files are only read, never changed."""
        import shutil
        import tempfile

        src = Path(collection)
        if any(p["path"] == str(src) and p["locked"] for p in self.anki_profiles()):
            raise ValueError("Anki ist noch geöffnet. Bitte Anki schließen und erneut versuchen.")
        media = src.parent / "collection.media"
        tmp = Path(tempfile.mkdtemp())
        try:
            # work on a copy: opening a collection may upgrade its schema, Anki's original must stay untouched
            for suffix in ("", "-wal"):
                if Path(str(src) + suffix).exists():
                    shutil.copy2(str(src) + suffix, tmp / ("collection.anki2" + suffix))
            if mode == "replace":
                self._col.create_backup(backup_folder=str(self._backup_dir()), force=True, wait_for_completion=True)
                dest = Path(self._col.path)
                self._col.close(downgrade=False)
                try:
                    for suffix in ("", "-wal"):
                        Path(str(dest) + suffix).unlink(missing_ok=True)
                    for suffix in ("", "-wal"):
                        if (tmp / ("collection.anki2" + suffix)).exists():
                            shutil.copy2(tmp / ("collection.anki2" + suffix), str(dest) + suffix)
                    if media.exists():
                        shutil.copytree(media, dest.parent / "collection.media", dirs_exist_ok=True)
                finally:
                    self._col = Collection(str(dest))
                    self._current = None
                return f"Anki-Sammlung übernommen: {self._col.card_count()} Karten. Dein vorheriger Stand liegt unter Sicherungen."
            # merge: export everything from the copy as .apkg (with media and scheduling) and import it here
            if media.exists():
                try:
                    (tmp / "collection.media").symlink_to(media, target_is_directory=True)
                except OSError:  # Windows without symlink rights
                    shutil.copytree(media, tmp / "collection.media")
            other = Collection(str(tmp / "collection.anki2"))
            try:
                other.export_anki_package(
                    out_path=str(tmp / "all.apkg"), limit=None,
                    options=ExportAnkiPackageOptions(with_scheduling=True, with_deck_configs=True, with_media=True, legacy=False),
                )
            finally:
                other.close(downgrade=False)
            log = self._col.import_anki_package(ImportAnkiPackageRequest(
                package_path=str(tmp / "all.apkg"),
                options=ImportAnkiPackageOptions(with_scheduling=True, with_deck_configs=True),
            )).log
            return f"Aus Anki zusammengeführt: {len(log.new)} neu, {len(log.updated)} aktualisiert, {len(log.duplicate)} schon vorhanden."
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---------- storage location ----------

    def storage(self) -> dict:
        d = Path(self._col.path).parent
        return {"dir": str(d), "default": str(data_dir()), "is_default": d == data_dir(), "synced_folder": looks_synced(d)}

    def pick_folder(self) -> str | None:
        import webview

        res = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return res[0] if res else None

    def check_storage_target(self, folder: str) -> dict:
        d = Path(folder)
        return {"has_collection": (d / "collection.anki2").exists(), "synced_folder": looks_synced(d),
                "same": d.resolve() == Path(self._col.path).parent.resolve()}

    @_locked
    def change_storage(self, folder: str, mode: str = "move") -> str:
        """mode 'move': copy the current collection (with media and backups) into folder and use it there;
        the old files stay where they were as a copy. mode 'open': switch to a collection already in folder."""
        import shutil

        target = Path(folder)
        src_dir = Path(self._col.path).parent
        if target.resolve() == src_dir.resolve():
            return "Das ist bereits der Speicherort."
        if mode == "move" and (target / "collection.anki2").exists():
            raise ValueError("Dort liegt schon eine Sammlung. Wähle „Vorhandene öffnen“ oder einen leeren Ordner.")
        if mode == "open" and not (target / "collection.anki2").exists():
            raise ValueError("In diesem Ordner liegt keine Sammlung (collection.anki2).")
        target.mkdir(parents=True, exist_ok=True)

        self._col.close(downgrade=False)
        try:
            if mode == "move":
                shutil.copy2(src_dir / "collection.anki2", target / "collection.anki2")
                for name in ("collection.media", "backups"):
                    if (src_dir / name).exists():
                        shutil.copytree(src_dir / name, target / name, dirs_exist_ok=True)
                if (src_dir / "collection.media.db2").exists():
                    shutil.copy2(src_dir / "collection.media.db2", target / "collection.media.db2")
            self._col = Collection(str(target / "collection.anki2"))
        except Exception:
            self._col = Collection(str(src_dir / "collection.anki2"))  # stay on the old one
            raise
        self._current = None
        save_config(collection_dir=None if target.resolve() == data_dir().resolve() else str(target))
        return f"Sammlung liegt jetzt in {target}" + (f". Die alte Kopie in {src_dir} kannst du löschen." if mode == "move" else "")

    # ---------- Claude ----------

    def claude_status(self) -> dict:
        from . import claude_connect

        return claude_connect.status()

    def connect_claude(self, target: str) -> str:
        """target: 'desktop' or 'code'."""
        from . import claude_connect

        return claude_connect.connect(target)

    def disconnect_claude(self, target: str) -> None:
        from . import claude_connect

        claude_connect.disconnect(target)

    # ---------- updates ----------

    def app_version(self) -> str:
        from . import __version__

        return __version__

    def check_update(self, manual: bool = False) -> dict | None:
        from . import updater

        return updater.check(manual)

    def update_failure(self) -> str | None:
        """Why the last update had to keep the old version, once, if it did."""
        from . import updater

        return updater.take_failure()

    def install_update(self) -> None:
        """Downloads the update, then quits; a helper swaps the app and starts it again."""
        from . import updater

        update = updater.check()
        if not update:
            raise RuntimeError("Kein Update verfügbar.")
        updater.install(update)
        threading.Timer(0.3, self._window.destroy).start()

    # ---------- native dialogs (app only) ----------

    def pick_import_file(self) -> str | None:
        import webview

        res = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=("Anki und CSV (*.apkg;*.colpkg;*.csv;*.txt;*.tsv)",))
        return res[0] if res else None

    def pick_export_file(self, name: str, ext: str = "apkg") -> str | None:
        import webview

        res = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=f"{name}.{ext}")
        return (res if isinstance(res, str) else res[0]) if res else None

    def media_dir(self) -> str:
        return self._col.media.dir()
