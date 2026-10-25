#!/bin/sh
# Adds the worker to the built web app (ui/dist-web), so one `vercel deploy ui/dist-web` ships both.
# api/_lib is not a route (Vercel skips names starting with _), it's the worker's import path.
set -e
cd "$(dirname "$0")/.."
out=ui/dist-web
lib=$out/api/_lib
mkdir -p "$lib/muisti"
cp web-api/worker.py web-api/connector.py "$out/api/"
cp src/muisti/__init__.py src/muisti/core.py src/muisti/cloud.py src/muisti/server.py src/muisti/mcp_server.py "$lib/muisti/"
cp web-api/requirements.txt "$out/requirements.txt"
echo 3.12 > "$out/.python-version"
version=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)
anki=$(awk '$0=="name = \"anki\""{getline; print; exit}' uv.lock | sed 's/version = //; s/"//g')
# the Linux x86_64 wheel straight from PyPI (no pip needed), unpacked into the worker's import path
python3 - "$anki" "$lib" <<'PY'
import io, json, sys, urllib.request, zipfile
version, lib = sys.argv[1:]
files = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/anki/{version}/json"))["urls"]
url = next(f["url"] for f in files if f["filename"].endswith("manylinux_2_35_x86_64.whl"))
zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(url).read())).extractall(lib)
PY
echo "worker bundled (muisti $version, anki $anki)"
