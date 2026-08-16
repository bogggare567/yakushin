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
import socket
import subprocess
import sys
import threading
import time


def local_addresses():
    """Every IPv4 address this machine answers on, best guess first.

    A laptop rarely has one. Windows in particular carries adapters for
    VirtualBox, WSL, Hyper-V and any VPN, and picking the wrong one produces a
    QR code that scans perfectly and then hangs forever - which is exactly what
    "не открывается на телефоне" looks like from the phone's side.

    The first entry is found by asking the routing table which address this
    machine would use to reach the outside world; that is the one the phone on
    the same Wi-Fi can also reach. The rest are offered as fallbacks rather
    than guessed between.
    """
    out = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))     # no packet is sent; this only picks a route
        out.append(s.getsockname()[0])
    except OSError:
        pass
    finally:
        s.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in out and not ip.startswith("127."):
                out.append(ip)
    except OSError:
        pass
    return out


PEERS = {}          # ip -> when it was last heard from
PEERS_LOCK = threading.Lock()
OWN_ADDRS = set()   # filled once at startup; every request is checked against it


def note_peer(ip):
    """Remember that some other device really did reach us.

    This is the whole answer to "did the phone connect?", which until now
    nobody could see: the computer showed a QR code and then said nothing,
    whether the phone arrived or a firewall ate it.
    """
    if not ip or ip.startswith("127.") or ip == "::1" or ip in OWN_ADDRS:
        return
    with PEERS_LOCK:
        PEERS[ip] = time.time()


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
RESULTS = {"version": 0, "data": None}
RESULTS_LOCK = threading.Lock()
PDF_STORE = {"version": 0, "bytes": None, "name": None}


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # SimpleHTTPRequestHandler sends no Cache-Control at all, so browsers
        # fall back to heuristic caching and happily keep serving a stale
        # app.js/style.css after an update. That produces a half-updated app -
        # new markup with old styling - which looks like random breakage
        # (unstyled blue buttons, dialogs rendering as plain page content)
        # rather than a caching problem. Always revalidate; Last-Modified
        # still lets unchanged files come back as a cheap 304.
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        super().end_headers()

    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        note_peer(self.client_address[0])
        if self.path.startswith("/api/peers"):
            # who else has reached this server, and how recently
            now = time.time()
            with PEERS_LOCK:
                seen = [{"ip": ip, "agoMs": int((now - t) * 1000)} for ip, t in PEERS.items()]
            self._send_json({"peers": sorted(seen, key=lambda p: p["agoMs"])})
            return
        if self.path.startswith("/api/info"):
            # The Wi-Fi IP is handed out by the router and changes between
            # sessions, which silently breaks any link bookmarked on a phone.
            # The Bonjour/mDNS ".local" name does not change, so offer it as
            # the address worth saving.
            self._send_json({"stableHost": stable_hostname(),
                             "port": self.server.server_address[1],
                             "addresses": local_addresses()})
            return
        if self.path.startswith("/api/state"):
            with STATE_LOCK:
                self._send_json(STATE)
            return
        if self.path.startswith("/api/results/meta"):
            with RESULTS_LOCK:
                self._send_json({"version": RESULTS["version"],
                                 "hasResults": RESULTS["data"] is not None})
            return
        if self.path.startswith("/api/results"):
            with RESULTS_LOCK:
                data = RESULTS["data"]
                version = RESULTS["version"]
            if data is None:
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps({"version": version, "data": data}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
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
        note_peer(self.client_address[0])
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
        if self.path.startswith("/api/results"):
            # The finished parts list, so the phone can show it without ever
            # receiving the PDF or doing the work again. It is the computer that
            # has the file and the time; the phone is a remote control.
            try:
                data = json.loads(body.decode("utf-8")) if body else None
            except (ValueError, UnicodeDecodeError):
                data = None
            with RESULTS_LOCK:
                RESULTS["data"] = data
                RESULTS["version"] += 1
                resp = {"version": RESULTS["version"]}
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
    # `--addresses` exists so a launcher script never has to parse ipconfig and
    # guess which of a machine's adapters the phone can reach: taking the last
    # IPv4 line, which Start.bat used to do, lands on VirtualBox or WSL as
    # often as on Wi-Fi.
    if "--addresses" in sys.argv:
        print("\n".join(local_addresses()))
        sys.exit(0)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8934
    webapp_dir = sys.argv[2] if len(sys.argv) > 2 else "."
    os.chdir(webapp_dir)
    OWN_ADDRS.update(local_addresses())
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Serving {os.path.abspath(webapp_dir)} on 0.0.0.0:{port}")
    for ip in local_addresses():
        print(f"  http://{ip}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
