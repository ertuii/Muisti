"""Desktop Google sign-in: the browser comes back to the local port with ?code=, which is traded for a session (PKCE)."""

import base64
import hashlib
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from muisti import cloud  # noqa: E402

opened, sent = {}, {}


def browser(url):  # plays Google + Supabase: redirect straight back with a code
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    opened.update(q)
    threading.Thread(target=lambda: urllib.request.urlopen(q["redirect_to"] + "?code=abc").read()).start()


def http(method, path, body=None, **_):
    sent.update(path=path, body=body)
    return {"user": {"email": "g@example.com", "id": "u1"}, "access_token": "a", "refresh_token": "r", "expires_in": 3600}


webbrowser.open, cloud._http = browser, http
acc = cloud.Account(Path(tempfile.mkdtemp()))
assert acc.login_google(timeout=10) == "g@example.com"
assert opened["provider"] == "google" and opened["redirect_to"].startswith("http://127.0.0.1:")
assert sent["path"] == "/auth/v1/token?grant_type=pkce" and sent["body"]["auth_code"] == "abc"
challenge = base64.urlsafe_b64encode(hashlib.sha256(sent["body"]["code_verifier"].encode()).digest()).rstrip(b"=").decode()
assert opened["code_challenge"] == challenge
assert acc.load()["email"] == "g@example.com"
print("test_google_login: ok")
