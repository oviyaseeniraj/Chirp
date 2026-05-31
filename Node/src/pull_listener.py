#!/usr/bin/env python3
import json
import logging
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, urlunsplit
from pathlib import PurePosixPath

HOST = os.getenv("PULL_LISTENER_HOST", "0.0.0.0")
PORT = int(os.getenv("PULL_LISTENER_PORT", "5055"))
REPO_DIR = os.getenv("PULL_REPO_DIR", "/home/chirp/Chirp")
BRANCH = os.getenv("PULL_BRANCH", "main")
SERVICE_NAME = os.getenv("PULL_SERVICE_NAME", "chirp-launcher.service")

# GitHub token used only for git fetch
PULL_TOKEN = os.getenv("PULL_TOKEN", "")

# Server token used only to authorize HTTP pull requests
SERVER_AUTH_TOKEN = os.getenv("SERVER_AUTH_TOKEN", "")

logging.basicConfig(
    level=os.getenv("PULL_LISTENER_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("pull-listener")

_DEPLOY_LOCK = threading.Lock()


def _mask_token(value: str) -> str:
    return "***" if value else ""


def _remote_to_https(remote: str) -> str:
    if remote.startswith(("http://", "https://")):
        return remote

    # git@github.com:owner/repo.git -> https://github.com/owner/repo.git
    if remote.startswith("git@") and ":" in remote:
        host_part, path_part = remote.split(":", 1)
        host = host_part.split("@", 1)[1]
        return f"https://{host}/{path_part}"

    # ssh://git@github.com/owner/repo.git -> https://github.com/owner/repo.git
    if remote.startswith("ssh://"):
        parts = urlsplit(remote)
        host = parts.hostname or ""
        path = parts.path.lstrip("/")
        return f"https://{host}/{path}"

    return remote


def _git_fetch_command() -> list[str]:
    remote = subprocess.run(
        ["git", "-C", REPO_DIR, "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    logger.info("origin remote: %s", remote)

    if PULL_TOKEN:
        https_remote = _remote_to_https(remote)
        if https_remote.startswith(("http://", "https://")):
            parts = urlsplit(https_remote)
            netloc = parts.netloc
            if "@" in netloc:
                netloc = netloc.split("@", 1)[1]

            auth_url = urlunsplit(
                (parts.scheme, f"x-access-token:{PULL_TOKEN}@{netloc}", parts.path, parts.query, parts.fragment)
            )
            logger.info("Using token-authenticated fetch URL: %s", auth_url.replace(PULL_TOKEN, "***"))
            return ["git", "-C", REPO_DIR, "fetch", auth_url, BRANCH]

        logger.warning("Could not convert origin remote to HTTPS; falling back to origin")

    return ["git", "-C", REPO_DIR, "fetch", "origin", BRANCH]


def run(cmd):
    safe_cmd = [c.replace(PULL_TOKEN, _mask_token(PULL_TOKEN)) if PULL_TOKEN else c for c in cmd]
    logger.info("Running command: %s", " ".join(safe_cmd))
    p = subprocess.run(cmd, capture_output=True, text=True, check=True)
    if p.stdout.strip():
        logger.info("stdout: %s", p.stdout.strip())
    if p.stderr.strip():
        logger.info("stderr: %s", p.stderr.strip())
    return {"cmd": " ".join(safe_cmd), "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}


def do_deploy():
    logger.info("Starting deploy")
    steps = []
    steps.append(run(["git", "config", "--global", "--add", "safe.directory", REPO_DIR]))
    steps.append(run(["systemctl", "stop", SERVICE_NAME]))
    steps.append(run(_git_fetch_command()))
    steps.append(run(["git", "-C", REPO_DIR, "reset", "--hard", f"origin/{BRANCH}"]))
    steps.append(run(["git", "-C", REPO_DIR, "clean", "-fd"]))
    steps.append(run(["systemctl", "start", SERVICE_NAME]))
    steps.append(run(["systemctl", "is-active", SERVICE_NAME]))
    logger.info("Deploy completed")
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
        logger.info("Incoming POST %s from %s", self.path, self.client_address[0])

        if self.path != "/pull":
            logger.warning("Rejected request: invalid path %s", self.path)
            self.send_response(404)
            self._cors()
            self.end_headers()
            return

        if SERVER_AUTH_TOKEN:
            auth = self.headers.get("Authorization", "")
            if auth != f"Bearer {SERVER_AUTH_TOKEN}":
                logger.warning("Unauthorized request from %s", self.client_address[0])
                self.send_response(401)
                self._cors()
                self.end_headers()
                self.wfile.write(b'{"ok":false,"error":"unauthorized"}')
                return

        if not _DEPLOY_LOCK.acquire(blocking=False):
            logger.warning("Deploy already running")
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
            logger.exception("Deploy failed")
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
        logger.info("%s - %s", self.client_address[0], fmt % args)


if __name__ == "__main__":
    logger.info("pull-listener starting on %s:%s", HOST, PORT)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.serve_forever()