import json
import sys

import webview
from webview.dom import DOMEventHandler

from . import claude_connect, server
from .core import Core


def _hide_titlebar(window):
    """macOS: no title bar, the page reaches up to the window buttons (the UI keeps a drag strip there)."""
    import AppKit
    from PyObjCTools import AppHelper

    def apply():
        w = window.native
        w.setTitleVisibility_(AppKit.NSWindowTitleHidden)
        w.setTitlebarAppearsTransparent_(True)
        w.setStyleMask_(w.styleMask() | AppKit.NSWindowStyleMaskFullSizeContentView)

    AppHelper.callAfter(apply)  # AppKit only from the main thread


def _bind(window):
    """Runs once the window is up: title bar, file drag & drop and keeping Claude's paths current."""
    if sys.platform == "darwin":
        _hide_titlebar(window)

    def on_drop(e):
        # pywebview only hands out real file paths to Python-side drop handlers
        paths = [f.get("pywebviewFullPath") for f in e.get("dataTransfer", {}).get("files", [])]
        if paths := [p for p in paths if p]:
            window.evaluate_js(f"window.__baImport && window.__baImport({json.dumps(paths[0])})")

    window.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, True, debounce=500)
    window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
    claude_connect.refresh_paths()


def run():
    core = Core()
    core.mix_subdecks_by_default()
    url = server.start(core) + ("?mac" if sys.platform == "darwin" else "")  # the UI leaves room for the window buttons
    core._window = webview.create_window("Muisti", url, js_api=core, width=1200, height=820, min_size=(720, 540))
    try:
        webview.start(_bind, (core._window,))
    finally:
        server.stop()
        try:
            core.cloud_sync()  # what was learned last makes it online before the laptop closes
        except Exception:
            pass  # offline: the next start syncs it
        try:
            core.backup(force=False)  # Anki's periodic backup: skipped if the last one is recent
        finally:
            core._close()
