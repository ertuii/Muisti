import sys

__version__ = "0.12.0"  # keep in sync with pyproject.toml; a release tag is v<this>


def _selfcheck() -> None:
    """CI smoke test of the built app: load the GUI backend (on Windows the .NET parts) without opening a window.
    Exit code 0/1; the error goes to the file named after the flag, since a windowed exe has no console."""
    import traceback

    try:
        if sys.platform == "win32":
            import webview.platforms.edgechromium  # noqa: F401  WebView2 assemblies
            import webview.platforms.winforms  # noqa: F401  pythonnet + WinForms
        else:
            import webview.platforms.cocoa  # noqa: F401
    except Exception:
        with open(sys.argv[sys.argv.index("--selfcheck") + 1], "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        sys.exit(1)
    sys.exit(0)


def main() -> None:
    if "--selfcheck" in sys.argv:
        _selfcheck()
    if "--mcp" in sys.argv:
        from .mcp_server import run
    else:
        from .app import run
    run()
