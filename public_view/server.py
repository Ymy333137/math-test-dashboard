"""Static allowlist server with one limited snapshot refresh operation."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import json
from refresh_client import refresh

ROOT = Path("/public")
FILES = {"/": ("index.html", "text/html; charset=utf-8"),
         "/style.css": ("style.css", "text/css; charset=utf-8"),
         "/view.js": ("view.js", "text/javascript; charset=utf-8"),
         "/snapshot.json": ("snapshot.json", "application/json; charset=utf-8")}


class Handler(BaseHTTPRequestHandler):
    timeout = 10

    def do_GET(self):
        entry = FILES.get(urlsplit(self.path).path)
        if not entry:
            self.send_error(404)
            return
        try:
            body = (ROOT / entry[0]).read_bytes()
        except FileNotFoundError:
            self.send_error(503, "Snapshot unavailable")
            return
        self.send_response(200)
        self.send_header("Content-Type", entry[1])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_HEAD = do_GET

    def reject_write(self):
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        if self.path != "/refresh":
            self.reject_write()
            return
        if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Length", "0") != "0":
            self.send_error(400)
            return
        try:
            status, result = refresh("/refresh-public/refresh.sock")
        except (OSError, ValueError):
            status, result = 503, {"message": "更新暂未完成，请稍后重试"}
        body = json.dumps(result, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    do_PUT = do_PATCH = do_DELETE = do_OPTIONS = reject_write


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
