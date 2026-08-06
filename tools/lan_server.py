#!/usr/bin/env python3
"""Local LAN server for webapp/: serves the static site exactly like
`python -m http.server`, plus a tiny JSON+binary API so two devices on the
same Wi-Fi (e.g. phone + laptop) can share navigation state and the loaded
PDF - the phone can drive the laptop's screen, or hand it a PDF, and vice
versa. Everything lives in memory for the life of the process; nothing is
written to disk, and nothing leaves the local network.

Usage: python3 lan_server.py [port] [webapp_dir]
"""
import http.server
import json
import os
import subprocess
import sys
import threading

def stable_hostname():
    """The machine's Bonjour/mDNS name (e.g. "MacBook-Air-Bogdan.local"), which
    stays the same even when the router hands out a different IP. Returns None
    where that isn't available, in which case callers fall back to the IP."""
    try:
        name = subprocess.run(["scutil", "--get", "LocalHostName"],
                              capture_output=True, text=True, timeout=2).stdout.strip()
        return f"{name}.local" if name else None
    except Exception:
        return None


STATE_LOCK = threading.Lock()
STATE = {"version": 0, "data": {}}
PDF_LOCK = threading.Lock()
PDF_STORE = {"version": 0, "bytes": None, "name": None}


class Handler(http.server.SimpleHTTPRequestHandler):
    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/info"):
            # The Wi-Fi IP is handed out by the router and changes between
            # sessions, which silently breaks any link bookmarked on a phone.
            # The Bonjour/mDNS ".local" name does not change, so offer it as
            # the address worth saving.
            self._send_json({"stableHost": stable_hostname(), "port": self.server.server_address[1]})
            return
        if self.path.startswith("/api/state"):
            with STATE_LOCK:
                self._send_json(STATE)
            return
        if self.path.startswith("/api/pdf/meta"):
            with PDF_LOCK:
                self._send_json({
                    "version": PDF_STORE["version"],
                    "name": PDF_STORE["name"],
                    "hasFile": PDF_STORE["bytes"] is not None,
                })
            return
        if self.path.startswith("/api/pdf"):
            with PDF_LOCK:
                data = PDF_STORE["bytes"]
            if data is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
            return
        super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        if self.path.startswith("/api/state"):
            try:
                data = json.loads(body.decode("utf-8")) if body else {}
            except (ValueError, UnicodeDecodeError):
                data = {}
            with STATE_LOCK:
                STATE["version"] += 1
                STATE["data"] = data
                resp = dict(STATE)
            self._send_json(resp)
            return
        if self.path.startswith("/api/pdf"):
            name = self.headers.get("X-File-Name", "instructions.pdf")
            with PDF_LOCK:
                PDF_STORE["bytes"] = body
                PDF_STORE["name"] = name
                PDF_STORE["version"] += 1
                resp = {"version": PDF_STORE["version"], "name": name}
            self._send_json(resp)
            return
        self.send_response(404)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-File-Name")
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet; real errors still surface via send_response codes


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8934
    webapp_dir = sys.argv[2] if len(sys.argv) > 2 else "."
    os.chdir(webapp_dir)
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Serving {os.path.abspath(webapp_dir)} on 0.0.0.0:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
