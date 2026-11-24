#!/bin/sh
# Ships the bundled web app (ui/dist-web after bundle.sh) to the server: the worker to ~/api (restarted), the static
# files to ~/web, which the Caddy in front serves. Server setup: web-api/muisti.service, web-api/Caddyfile.
set -e
cd "$(dirname "$0")/.."
host=${MUISTI_SERVER:-muisti@5.231.26.190}
out=ui/dist-web
rsync -az --delete "$out/api/" web-api/dev.py "$host:api/"
rsync -az "$out/requirements.txt" "$host:"
ssh "$host" 'uv pip install -q -p venv -r requirements.txt && sudo systemctl restart muisti'
rsync -az --delete --exclude /api --exclude /requirements.txt --exclude /.python-version --exclude /vercel.json \
  "$out/" "$host:web/"
echo "deployed to $host"
