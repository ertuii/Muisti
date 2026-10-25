"""Muisti as a remote MCP server (Vercel Python function at /api/connector, public as /mcp): claude.ai adds it as a
custom connector. (Not named mcp.py: next to the worker that would shadow the mcp package.)

The tools are the desktop's (muisti/mcp_server.py); only their `call` goes to the worker's Core instead of the app.
Sign-in is Supabase Auth's OAuth 2.1 server: claude.ai registers itself, the user approves on the web app's
/oauth/consent page, and the access token is an ordinary Supabase token, so the worker's RLS path applies as is.
"""

import os
import sys

import anyio.to_thread
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings

sys.path.insert(0, os.path.dirname(__file__))
import worker  # noqa: E402  (also puts muisti on the import path)
from muisti import cloud, mcp_server  # noqa: E402

# the public address claude.ai uses; MUISTI_WEB_URL overrides it (previews)
BASE = os.environ.get("MUISTI_WEB_URL") or ("https://app.muisti.de" if "VERCEL" in os.environ
                                            else "http://127.0.0.1:4323")  # web-api/dev.py
PATH = "/mcp"  # vercel.json rewrites it and the metadata path below to /api/connector
META = "/.well-known/oauth-protected-resource" + PATH

# local files on a shared server are other people's: nothing here may read or write a path
WEB_TOOLS_OFF = ("current_card", "import_file", "export_deck", "add_media")


def call(method: str, **args):
    token = get_access_token()
    if token is None:
        raise PermissionError("Nicht angemeldet")
    return worker.run(token.token, method, args, worker.MCP_ALLOWED)


class Verifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            uid = await anyio.to_thread.run_sync(worker.user_of, token)
        except PermissionError:
            return None
        return AccessToken(token=token, client_id="claude", scopes=[], subject=uid)


mcp = mcp_server.mcp
mcp._lowlevel_server.instructions = (
    "Muisti online: the user's Muisti account, the same collection as the web app and every synced device. "
    "A second Muisti connector (on this computer) holds the same cards; "
    "changes reach the desktop app only after its next sync (up to 5 minutes).")
mcp_server.call = call  # the tools look `call` up at call time
for name in WEB_TOOLS_OFF:
    mcp.remove_tool(name)


@mcp.tool()
def add_media(filename: str, url: str | None = None, data_base64: str | None = None) -> str:
    """Store an image or audio file (e.g. a diagram) in the collection's media folder.
    Exactly one source: an http(s) URL or base64 data. filename sets the name and extension.
    Returns the stored file name (may differ if the name was taken), for <img src="NAME"> or [sound:NAME] in a field."""
    return mcp_server.add_media(filename, url=url, data_base64=data_base64)


# ponytail: set after construction since the tools live on the desktop's server object; the SDK reads both
# only in streamable_http_app below
mcp.settings.auth = AuthSettings(issuer_url=f"{cloud.URL}/auth/v1", resource_server_url=BASE + PATH,
                                 validate_token_resource=False)  # Supabase tokens carry no resource; user_of checks them
mcp._token_verifier = Verifier()

_app = mcp.streamable_http_app(streamable_http_path=PATH, stateless_http=True, json_response=True,
                               host="0.0.0.0")  # no localhost DNS-rebinding guard: this runs behind Vercel's domain


async def app(scope, receive, send):
    """Vercel rewrites the root metadata path here; route it by what it asks for, whatever path arrives."""
    if scope["type"] == "http":
        scope = {**scope, "path": META if "oauth-protected-resource" in scope["path"] else PATH}
    await _app(scope, receive, send)
