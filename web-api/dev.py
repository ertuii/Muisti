"""Runs the worker locally on 127.0.0.1:4322 (vite preview proxies /api there) and the Claude connector on
127.0.0.1:4323/mcp (for the MCP Inspector). PYTHONPATH=src uv run python web-api/dev.py"""
import threading
from http.server import ThreadingHTTPServer

import uvicorn

from worker import handler

threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", 4322), handler).serve_forever, daemon=True).start()
uvicorn.run("connector:app", host="127.0.0.1", port=4323)
