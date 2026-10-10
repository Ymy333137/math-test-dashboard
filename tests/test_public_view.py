import importlib.util
import json
import tempfile
import threading
import unittest
import sys
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

import app

ROOT = Path(__file__).resolve().parents[1] / "public_view"
sys.path.insert(0, str(ROOT))


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


export = module("public_export", "export.py")
server = module("public_server", "server.py")
broker = module("refresh_service", "refresh_service.py")


class PublicProjectionTests(unittest.TestCase):
    def test_only_approved_fields_and_primitive_values_are_exported(self):
        item = {"question_id": "private-id", "book_id": "workbook_880", "display_id": "P2-(1)",
                "summary": "公开摘要", "secret": "DO_NOT_PUBLISH", "schedule_key": "PRIVATE_KEY",
                "page": {"nested_secret": "DO_NOT_PUBLISH"}}
        review = {"today": "2026-10-10", "book_ids": ["workbook_880"], "queue": [item],
                  "summary": {"due_total": 1, "book_counts": {}, "secret": "DO_NOT_PUBLISH"},
                  "settings": {"daily_limit": 20, "secret": "DO_NOT_PUBLISH"}}
        state = {"items": {"private-id": {"history": [{"note": "公开 comment", "secret": "DO_NOT_PUBLISH"}]}}}
        result = export.project(review, state, [])
        serialized = json.dumps(result)
        self.assertNotIn("DO_NOT_PUBLISH", serialized)
        self.assertNotIn("PRIVATE_KEY", serialized)
        self.assertNotIn("private-id", serialized)
        self.assertNotIn("page", result["queue"][0])
        self.assertEqual(result["queue"][0]["note"], "公开 comment")

    def test_read_only_review_does_not_initialize_or_save_schedule(self):
        schedule = {"buckets": {}, "daily_plans": {}, "backlog": []}
        state = {"settings": {"daily_limit": 20}, "items": {}}
        with patch.object(app, "load_index", return_value={}), \
             patch.object(app, "load_review_state", return_value=state), \
             patch.object(app, "load_reviewable_book_records", return_value={}), \
             patch.object(app, "load_review_schedule", return_value=schedule), \
             patch.object(app, "tier_groups", return_value=[]), \
             patch.object(app, "ensure_review_schedule", side_effect=AssertionError("schedule write path")), \
             patch.object(app, "write_json", side_effect=AssertionError("write")):
            payload = app.build_review_payload(read_only=True)
        self.assertEqual(payload["queue"], [])
        self.assertEqual(schedule, {"buckets": {}, "daily_plans": {}, "backlog": []})


class PublicHTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root_patch = patch.object(server, "ROOT", Path(self.directory.name))
        self.root_patch.start()
        for _, (name, _) in server.FILES.items():
            (server.ROOT / name).write_text("{}" if name.endswith("json") else "public")
        (server.ROOT / "private.txt").write_text("secret")
        self.http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.root_patch.stop()
        self.directory.cleanup()

    def request(self, method, path, body=None):
        connection = HTTPConnection("127.0.0.1", self.http.server_port)
        connection.request(method, path, body=body)
        response = connection.getresponse()
        body = response.read()
        result = response.status, dict(response.getheaders()), body
        connection.close()
        return result

    def test_only_four_static_routes_are_readable(self):
        for path in server.FILES:
            self.assertEqual(self.request("GET", path)[0], 200)
        for path in ("/api/review/today", "/api/dashboard", "/review_state.json", "/.env",
                     "/private.txt", "/../private.txt", "/%2e%2e/private.txt", "/static/"):
            self.assertEqual(self.request("GET", path)[0], 404)

    def test_mutations_are_rejected(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            for path in ("/snapshot.json", "/api/git/commit", "/api/review/feedback"):
                self.assertEqual(self.request(method, path)[0], 405)

    def test_browser_security_headers_and_head(self):
        status, headers, body = self.request("HEAD", "/")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_public_refresh_forwards_only_to_limited_socket(self):
        with patch.object(server, "refresh", return_value=(429, {"message": "CD 5 分钟"})) as refresh:
            status, _, body = self.request("POST", "/refresh")
            self.assertEqual(status, 429)
            self.assertIn("CD 5 分钟", json.loads(body)["message"])
            refresh.assert_called_once_with("/refresh-public/refresh.sock")
        self.assertEqual(self.request("POST", "/refresh?private=1")[0], 405)
        self.assertEqual(self.request("GET", "/refresh")[0], 404)

    def test_refresh_rejects_caller_parameters_and_backend_failure(self):
        with patch.object(server, "refresh", side_effect=OSError("unavailable")) as refresh:
            self.assertEqual(self.request("POST", "/refresh", b'{"private":true}')[0], 400)
            refresh.assert_not_called()
            self.assertEqual(self.request("POST", "/refresh")[0], 503)


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.cooldown = patch.object(broker, "COOLDOWN_FILE", Path(self.directory.name) / "last")
        self.cooldown.start()

    def tearDown(self):
        self.cooldown.stop()
        self.directory.cleanup()

    def test_public_cooldown_and_unlimited_private_refresh(self):
        with patch.object(broker, "run_export") as export, patch.object(broker.time, "time", return_value=1000):
            self.assertEqual(broker.request_refresh(True)[0], 200)
            self.assertEqual(broker.request_refresh(True)[0], 429)
            self.assertEqual(broker.request_refresh(False)[0], 200)
            self.assertEqual(broker.request_refresh(False)[0], 200)
            self.assertEqual(export.call_count, 3)
        with patch.object(broker, "run_export"), patch.object(broker.time, "time", return_value=1300):
            self.assertEqual(broker.request_refresh(True)[0], 200)

    def test_failure_retains_snapshot_and_limits_repeated_failures(self):
        with patch.object(broker, "run_export", side_effect=OSError("failed")):
            self.assertEqual(broker.request_refresh(True)[0], 503)
            self.assertEqual(broker.request_refresh(True)[0], 429)

    def test_concurrent_requests_share_export(self):
        entered, finish = threading.Event(), threading.Event()
        results = []
        def slow_export():
            entered.set()
            finish.wait(2)
        with patch.object(broker, "run_export", side_effect=slow_export) as export:
            first = threading.Thread(target=lambda: results.append(broker.request_refresh(False)))
            first.start()
            self.assertTrue(entered.wait(1))
            second = threading.Thread(target=lambda: results.append(broker.request_refresh(True)))
            second.start()
            finish.set()
            first.join()
            second.join()
            self.assertEqual(export.call_count, 1)
            self.assertEqual([r[0] for r in results], [200, 200])

    def test_private_api_requires_configured_socket(self):
        with patch.dict(app.os.environ, {}, clear=True):
            with self.assertRaises(app.HTTPException) as error:
                app.api_public_snapshot_refresh()
            self.assertEqual(error.exception.status_code, 503)
        with patch.dict(app.os.environ, {"PUBLIC_REFRESH_SOCKET": "/private/socket"}), \
             patch.object(app, "refresh_public_snapshot", return_value=(200, {"message": "ok"})) as refresh:
            self.assertEqual(app.api_public_snapshot_refresh().status_code, 200)
            refresh.assert_called_once_with("/private/socket")


if __name__ == "__main__":
    unittest.main()
