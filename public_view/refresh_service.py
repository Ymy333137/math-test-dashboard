"""Host-only broker: two separate sockets, one fixed export command."""
import json
import os
import socketserver
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

PUBLIC_SOCKET = Path("/run/math-public-refresh/public/refresh.sock")
PRIVATE_SOCKET = Path("/run/math-public-refresh/private/refresh.sock")
COOLDOWN_FILE = Path("/var/lib/math-public-refresh/last-request")
LOCK = threading.Lock()
LAST_RESULT = 503, {"message": "快照尚未更新"}


def run_export():
    subprocess.run(["/usr/bin/docker", "compose", "run", "--rm", "exporter"],
                   cwd="/opt/math-public", check=True, timeout=100,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def request_refresh(public):
    global LAST_RESULT
    # Waiting callers share the running export instead of launching another one.
    if not LOCK.acquire(blocking=False):
        with LOCK:
            return LAST_RESULT
    try:
        if public:
            last = float(COOLDOWN_FILE.read_text()) if COOLDOWN_FILE.exists() else 0
            if time.time() - last < 300:
                return 429, {"message": "刷新技能冷却中，CD 5 分钟。"}
            COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
            COOLDOWN_FILE.write_text(str(time.time()))
        try:
            run_export()
            LAST_RESULT = 200, {"message": "公开副本已更新"}
        except (subprocess.SubprocessError, OSError):
            LAST_RESULT = 503, {"message": "更新暂未完成，原有快照仍可查看，请稍后重试"}
        return LAST_RESULT
    finally:
        LOCK.release()


class Handler(BaseHTTPRequestHandler):
    timeout = 10

    def log_message(self, format, *args):
        print(format % args, flush=True)

    def do_POST(self):
        if self.path != "/refresh" or self.headers.get("Transfer-Encoding") or self.headers.get("Content-Length", "0") != "0":
            self.send_error(400)
            return
        status, result = request_refresh(self.server.public)
        body = json.dumps(result, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main():
    for path, public in ((PUBLIC_SOCKET, True), (PRIVATE_SOCKET, False)):
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o755 if public else 0o700)
        path.unlink(missing_ok=True)
        server = Server(str(path), Handler)
        server.public = public
        os.chmod(path, 0o666 if public else 0o600)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Event().wait()


if __name__ == "__main__":
    main()
