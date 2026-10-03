import asyncio
import json
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import app


class ReviewActivityTests(unittest.TestCase):
    def setUp(self):
        self.today = date.today().isoformat()
        self.key = "workbook_660:660-1"

    def event(self, outcome="pass", book_id="workbook_660"):
        return {"reviewed_at": f"{self.today}T10:00:00", "outcome": outcome, "book_id": book_id}

    def activity(self, items, plan):
        return app.build_activity(
            {"items": items, "settings": {"daily_limit": 20}}, days=1,
            schedule={"daily_plans": {self.today: plan}},
        )[0]

    def test_small_plan_can_reach_full_completion(self):
        result = self.activity({"660-1": {"history": [self.event()]}}, [self.key])
        self.assertEqual((result["completed"], result["planned"], result["ratio"]), (1, 1, 1))

    def test_wrong_counts_as_review_and_duplicates_count_once(self):
        result = self.activity(
            {"660-1": {"history": [self.event("wrong"), self.event()]}},
            [self.key, self.key, "workbook_660:660-2"],
        )
        self.assertEqual(result["count"], 2)
        self.assertEqual((result["completed"], result["planned"], result["ratio"]), (1, 2, .5))

    def test_backlog_move_does_not_count_as_completion(self):
        schedule = {"daily_plans": {self.today: [self.key]}, "backlog": [self.key], "buckets": {}}
        result = app.build_activity({"items": {}}, days=1, schedule=schedule)[0]
        self.assertEqual(result["planned"], 1)
        self.assertEqual(result["ratio"], 0)

    def test_unplanned_reviews_do_not_inflate_completion(self):
        result = self.activity({"660-2": {"history": [self.event()]}}, [self.key])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["ratio"], 0)

    def test_missing_plan_keeps_count_without_inventing_a_ratio(self):
        result = self.activity({"660-1": {"history": [self.event()]}}, [])
        self.assertEqual(result["count"], 1)
        self.assertIsNone(result["ratio"])

    def test_legacy_event_and_structured_ids_use_schedule_identity(self):
        legacy = self.event()
        del legacy["book_id"]
        fill = "880-basic-fill-P2-(1)"
        solve = "880-basic-solve-P2-(1)"
        result = self.activity({
            "660-1": {"history": [legacy]},
            fill: {"history": [self.event(book_id="workbook_880")]},
            solve: {"history": []},
        }, [self.key, f"workbook_880:{fill}", f"workbook_880:{solve}"])
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["planned"], 3)


class ReviewHistoryWindowTests(unittest.TestCase):
    def test_two_calendar_days_keep_event_indexes_and_lifetime_total(self):
        today = date.today()
        yesterday = today - timedelta(days=1)
        dates = [today - timedelta(days=2), yesterday, today]
        state = {"items": {"660-1": {"book_id": "workbook_660", "history": [
            {"reviewed_at": f"{day.isoformat()}T23:59:00", "outcome": "wrong", "error_level": "B"}
            for day in dates
        ]}}}
        book = {"history": [{"question_id": "660-1", "error_level": "B"}], "records": []}
        with patch.object(app, "load_review_state", return_value=state), \
             patch.object(app, "load_index", return_value={}), \
             patch.object(app, "load_all_book_records", return_value={"workbook_660": book}), \
             patch.object(app, "load_review_schedule", return_value={"daily_plans": {}}):
            payload = json.loads(asyncio.run(app.api_review_history()).body)

        self.assertEqual(payload["start_date"], yesterday.isoformat())
        self.assertEqual(payload["total_reviews"], 3)
        self.assertEqual([item["event_index"] for item in payload["history"]], [2, 1])
        self.assertEqual([item["review_count"] for item in payload["history"]], [3, 2])
        self.assertEqual([item["fail_count"] for item in payload["history"]], [4, 3])


if __name__ == "__main__":
    unittest.main()
