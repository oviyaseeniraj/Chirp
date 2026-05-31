#!/usr/bin/env python3
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.getenv("PULL_LISTENER_HOST", "0.0.0.0")
PORT = int(os.getenv("PULL_LISTENER_PORT", "5055"))
REPO_DIR = os.getenv("PULL_REPO_DIR", "/home/chirp/Chirp")
BRANCH = os.getenv("PULL_BRANCH", "main")
SERVICE_NAME = os.getenv("PULL_SERVICE_NAME", "chirp-launcher.service")
TOKEN = os.getenv("PULL_TOKEN", "")  # optional but recommended

_DEPLOY_LOCK = threading.Lock()


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return {"cmd": " ".join(cmd), "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}


def do_deploy():
    steps = []
    steps.append(run(["systemctl", "stop", SERVICE_NAME]))
    steps.append(run(["git", "-C", REPO_DIR, "fetch", "origin", BRANCH]))
    steps.append(run(["git", "-C", REPO_DIR, "reset", "--hard", f"origin/{BRANCH}"]))
    steps.append(run(["git", "-C", REPO_DIR, "clean", "-fd"]))
    steps.append(run(["systemctl", "start", SERVICE_NAME]))
    steps.append(run(["systemctl", "is-active", SERVICE_NAME]))
    return steps


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if self.path != "/pull":
            self.send_response(404)
            self._cors()
            self.end_headers()
            return

        if TOKEN:
            auth = self.headers.get("Authorization", "")
            if auth != f"Bearer {TOKEN}":
                self.send_response(401)
                self._cors()
                self.end_headers()
                self.wfile.write(b'{"ok":false,"error":"unauthorized"}')
                return

        if not _DEPLOY_LOCK.acquire(blocking=False):
            self.send_response(409)
            self._cors()
            self.end_headers()
            self.wfile.write(b'{"ok":false,"error":"deploy already running"}')
            return

        try:
            steps = do_deploy()
            body = json.dumps({"ok": True, "steps": steps}).encode()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except subprocess.CalledProcessError as e:
            body = json.dumps({
                "ok": False,
                "error": "command failed",
                "cmd": " ".join(e.cmd) if isinstance(e.cmd, list) else str(e.cmd),
                "stdout": (e.stdout or "").strip(),
                "stderr": (e.stderr or "").strip()
            }).encode()
            self.send_response(500)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        finally:
            _DEPLOY_LOCK.release()

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"pull-listener on {HOST}:{PORT}")
    httpd.serve_forever()