import asyncio
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import app


class YesterdayBacklogTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for name, filename in [
            ("INDEX_FILE", "math_records.json"),
            ("REVIEW_STATE_FILE", "review_state.json"),
            ("REVIEW_SCHEDULE_FILE", "review_schedule.json"),
        ]:
            override = patch.object(app, name, root / filename)
            override.start()
            self.addCleanup(override.stop)
        app.write_json(app.INDEX_FILE, {"record_files": {}})
        app.write_json(app.REVIEW_STATE_FILE, app.default_review_state())
        self.today = date.today()
        self.yesterday = self.today - timedelta(days=1)
        self.older = self.today - timedelta(days=3)

    def test_loading_today_keeps_past_buckets_without_moving_them(self):
        schedule = app.default_review_schedule()
        schedule["buckets"] = {
            self.older.isoformat(): ["workbook_660:660-1"],
            self.yesterday.isoformat(): ["workbook_880:880-yesterday"],
        }
        app.save_review_schedule(schedule)
        before = app.REVIEW_SCHEDULE_FILE.read_bytes()

        app.ensure_review_schedule({}, app.load_review_state(), self.today)

        self.assertEqual(app.REVIEW_SCHEDULE_FILE.read_bytes(), before)
        self.assertEqual(app.load_review_schedule()["backlog"], [])

    def test_button_moves_only_yesterday_and_preserves_state_and_plans(self):
        key_660 = "workbook_660:660-2"
        key_880 = "workbook_880:880-basic-fill-P2-(1)"
        schedule = app.default_review_schedule()
        schedule["buckets"] = {
            self.older.isoformat(): ["workbook_660:660-1"],
            self.yesterday.isoformat(): [key_660, key_880, key_660],
            self.today.isoformat(): ["workbook_660:660-3"],
        }
        schedule["daily_plans"] = {self.yesterday.isoformat(): [key_660, key_880]}
        schedule["forced_releases"] = {self.yesterday.isoformat(): [key_660]}
        app.save_review_schedule(schedule)
        state_before = app.REVIEW_STATE_FILE.read_bytes()

        response = asyncio.run(app.api_review_backlog_yesterday())
        result = json.loads(response.body)
        after = app.load_review_schedule()

        self.assertEqual(result, {"date": self.yesterday.isoformat(), "moved": 2, "backlog_total": 2})
        self.assertEqual(after["backlog"], [key_660, key_880])
        self.assertNotIn(self.yesterday.isoformat(), after["buckets"])
        self.assertEqual(after["buckets"][self.older.isoformat()], ["workbook_660:660-1"])
        self.assertEqual(after["buckets"][self.today.isoformat()], ["workbook_660:660-3"])
        self.assertEqual(after["daily_plans"], schedule["daily_plans"])
        self.assertNotIn(self.yesterday.isoformat(), after["forced_releases"])
        self.assertEqual(app.REVIEW_STATE_FILE.read_bytes(), state_before)

    def test_existing_destinations_and_completed_reviews_are_not_repeated(self):
        keys = {name: f"workbook_660:660-{name}" for name in [
            "remaining", "backlog", "today", "future", "buffered", "reviewed", "reviewed-today",
        ]}
        schedule = app.default_review_schedule()
        future = self.today + timedelta(days=5)
        schedule["buckets"] = {
            self.yesterday.isoformat(): list(keys.values()),
            self.today.isoformat(): [keys["today"]],
            future.isoformat(): [keys["future"]],
        }
        schedule["backlog"] = [keys["backlog"]]
        schedule["release_buffer"] = {self.older.isoformat(): [keys["buffered"]]}
        app.save_review_schedule(schedule)
        state = app.default_review_state()
        state["items"] = {
            "660-reviewed": {"last_reviewed_at": self.yesterday.isoformat()},
            "660-reviewed-today": {"last_reviewed_at": self.today.isoformat()},
            "660-remaining": {"last_reviewed_at": self.older.isoformat()},
        }
        app.write_json(app.REVIEW_STATE_FILE, state)

        result = app.move_yesterday_to_backlog()
        after = app.load_review_schedule()

        self.assertEqual(result["moved"], 1)
        self.assertEqual(after["backlog"], [keys["remaining"], keys["backlog"]])
        self.assertEqual(after["buckets"][self.today.isoformat()], [keys["today"]])
        self.assertEqual(after["buckets"][future.isoformat()], [keys["future"]])
        self.assertEqual(after["release_buffer"], schedule["release_buffer"])
        self.assertEqual(app.read_json(app.REVIEW_STATE_FILE), state)

    def test_repeated_click_does_not_write_again(self):
        schedule = app.default_review_schedule()
        schedule["buckets"] = {self.yesterday.isoformat(): ["workbook_660:660-1"]}
        app.save_review_schedule(schedule)
        app.move_yesterday_to_backlog()
        before = app.REVIEW_SCHEDULE_FILE.read_bytes()

        with patch.object(app, "load_review_state", side_effect=AssertionError("No remaining questions")), \
             patch.object(app, "save_review_schedule", side_effect=AssertionError("Nothing to save")):
            result = app.move_yesterday_to_backlog()

        self.assertEqual(result["moved"], 0)
        self.assertEqual(result["backlog_total"], 1)
        self.assertEqual(app.REVIEW_SCHEDULE_FILE.read_bytes(), before)

    def test_missing_yesterday_does_not_restore_historical_plan(self):
        schedule = app.default_review_schedule()
        schedule["buckets"] = {self.older.isoformat(): ["workbook_660:660-1"]}
        schedule["daily_plans"] = {self.yesterday.isoformat(): ["workbook_660:660-2"]}
        app.save_review_schedule(schedule)
        before = app.REVIEW_SCHEDULE_FILE.read_bytes()

        result = app.move_yesterday_to_backlog()

        self.assertEqual(result["moved"], 0)
        self.assertEqual(app.REVIEW_SCHEDULE_FILE.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
