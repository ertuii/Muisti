"""Claude connector (web-api/connector.py): sign-in is required, tool calls reach the worker as the token's user,
and tools that touch local files are not offered. The worker itself is stubbed, no Supabase needed."""

import os
import sys
import tempfile
from pathlib import Path

root = Path(__file__).parents[1]
sys.path[:0] = [str(root / "src"), str(root / "web-api")]
os.environ["MUISTI_DIR"] = tempfile.mkdtemp()

from starlette.testclient import TestClient  # noqa: E402

import connector  # noqa: E402
import worker  # noqa: E402

calls = []
worker.user_of = lambda token: "user-1" if token == "good" else (_ for _ in ()).throw(PermissionError("Nicht angemeldet"))
worker.run = lambda token, method, args, allowed: calls.append((token, method, args, allowed)) or [{"name": "Analysis"}]

HEAD = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}


def rpc(c, method, params=None, token="good"):
    h = {**HEAD, **({"Authorization": f"Bearer {token}"} if token else {})}
    return c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, headers=h)


with TestClient(connector.app) as c:
    assert rpc(c, "tools/list", token=None).status_code == 401
    assert rpc(c, "tools/list", token="bad").status_code == 401
    assert "oauth-protected-resource" in rpc(c, "tools/list", token=None).headers["www-authenticate"]
    assert c.get("/.well-known/oauth-protected-resource/mcp").json()["authorization_servers"][0].endswith("/auth/v1")

    names = {t["name"] for t in rpc(c, "tools/list").json()["result"]["tools"]}
    assert "add_notes" in names and "list_decks" in names
    assert not names & {"current_card", "import_file", "export_deck"}, names
    media = next(t for t in rpc(c, "tools/list").json()["result"]["tools"] if t["name"] == "add_media")
    assert "path" not in media["inputSchema"]["properties"]

    r = rpc(c, "tools/call", {"name": "list_decks", "arguments": {}}).json()
    assert not r["result"].get("isError"), r
    assert calls[-1] == ("good", "decks", {}, worker.MCP_ALLOWED)

    rpc(c, "tools/call", {"name": "add_notes", "arguments": {"notes": [{"deck": "A", "fields": {"Front": "x", "Back": "y"}}]}})
    assert calls[-1][1] == "add_note" and calls[-1][2]["inbox"] is True

# every method a tool calls must be allowed for the connector, and none that reads or writes files
assert worker.MCP_ALLOWED.isdisjoint({"import_file", "export_deck", "export_collection", "current_card"})
print("test_connector: ok")
