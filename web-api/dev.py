"""Runs the worker on :4322 (vite preview proxies /api there) and the Claude connector on :4323/mcp, in one process
so both share the warm collections. Locally: PYTHONPATH=src uv run python web-api/dev.py. On the server
(web-api/muisti.service) MUISTI_BIND puts both on the Docker bridge, where the Caddy in front reaches them."""
import os
import threading
from http.server import ThreadingHTTPServer

import uvicorn

from worker import handler

HOST = os.environ.get("MUISTI_BIND", "127.0.0.1")
threading.Thread(target=ThreadingHTTPServer((HOST, 4322), handler).serve_forever, daemon=True).start()
uvicorn.run("connector:app", host=HOST, port=4323)
