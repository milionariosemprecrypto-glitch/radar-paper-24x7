#!/usr/bin/env python3
"""Render free web: HTTP /health on $PORT + paper bot supervisor."""
import os, threading, subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("PORT", "10000"))

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"ok":true,"service":"cripto-bot","modo":"PAPER"}\n'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass

def serve():
    HTTPServer(("0.0.0.0", PORT), H).serve_forever()

threading.Thread(target=serve, daemon=True).start()
os.environ.setdefault("BOT_CMD", "python bot.py")
os.environ.setdefault("PY", "python")
raise SystemExit(subprocess.call(["bash", "./run.sh"]))
