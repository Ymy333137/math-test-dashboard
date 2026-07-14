import unittest
from datetime import date, timedelta

import app


class Workbook880IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        records_dir = str(app.RECORDS_DIR)
        if records_dir == "/Users/y-mac/Documents/math-test_2/records":
            raise RuntimeError("测试必须使用 records 临时副本")

    def test_dashboard_and_structured_errors(self):
        dashboard = app.build_dashboard_payload()
        book = next(item for item in dashboard["books"] if item["book_id"] == "workbook_880")
        self.assertEqual(book["total"], 31)
        self.assertEqual(book["abc_counts"], {"A": 4, "B": 7, "C": 2})
        self.assertEqual(book["total"] - book["error_total"], 18)

        errors = app.build_book_errors("workbook_880")
        items = [item for unit in errors["units"] for level in unit["levels"].values() for item in level]
        self.assertEqual(len(items), 13)
        self.assertTrue(all(item["section"] and item["question_type"] and item["display_id"] for item in items))

    def test_internal_ids_and_record_order_are_stable(self):
        records = app.load_book_record("workbook_880")["records"]
        same_display = [record for record in records if record.get("display_id") == "P2-(1)"]
        self.assertGreaterEqual(len(same_display), 2)
        self.assertEqual(len({record["question_id"] for record in same_display}), len(same_display))
        self.assertIn("填空题", {record["question_type"] for record in same_display})
        self.assertIn("解答题", {record["question_type"] for record in same_display})

        subquestions = [record for record in records if record.get("parent_display_id") == "P2-(2)"]
        self.assertGreaterEqual(len(subquestions), 2)
        self.assertEqual(len({record["question_id"] for record in subquestions}), len(subquestions))

        keys = [app.schedule_key("workbook_880", record["question_id"]) for record in reversed(records[:8])]
        sorted_keys = app.sort_schedule_keys(keys)
        orders = [
            next(record["record_order"] for record in records if record["question_id"] == app.question_id_from_schedule_key(key))
            for key in sorted_keys
        ]
        self.assertEqual(orders, sorted(orders))

    def test_mixed_queue_feedback_and_history(self):
        record_660 = next(
            record
            for record in app.load_book_record("workbook_660")["history"]
            if record.get("error_level")
        )
        record_880 = next(
            record
            for record in app.load_book_record("workbook_880")["history"]
            if record.get("error_level")
        )
        state = app.load_review_state()
        item_state = state.setdefault("items", {}).setdefault(record_660["question_id"], {"history": []})
        item_state["book_id"] = "workbook_660"
        item_state["next_due_at"] = date.today().isoformat()
        item_state_880 = state["items"].setdefault(record_880["question_id"], {"history": []})
        item_state_880["book_id"] = "workbook_880"
        item_state_880["next_due_at"] = date.today().isoformat()
        app.save_review_state(state)

        key_660 = app.schedule_key("workbook_660", record_660["question_id"])
        key_880 = app.schedule_key("workbook_880", record_880["question_id"])
        schedule = app.load_review_schedule()
        app.add_schedule_key(schedule, date.today(), key_660, replace=True)
        app.add_schedule_key(schedule, date.today(), key_880, replace=True)
        app.add_daily_plan_keys(schedule, date.today(), [key_660, key_880])
        app.save_review_schedule(schedule)

        payload = app.build_review_payload(daily_limit=200)
        queue_books = {item["book_id"] for item in payload["queue"]}
        self.assertTrue({"workbook_660", "workbook_880"}.issubset(queue_books))
        item_660 = next(
            item
            for item in payload["queue"]
            if item["book_id"] == "workbook_660" and item["question_id"] == record_660["question_id"]
        )
        item_880 = next(
            item
            for item in payload["queue"]
            if item["book_id"] == "workbook_880" and item["question_id"] == record_880["question_id"]
        )
        self.assertEqual(
            [item_880["section"], item_880["question_type"], item_880["display_id"]],
            [record_880["section"], record_880["question_type"], record_880["display_id"]],
        )

        state_before = app.load_review_state()
        history_660_before = len(state_before["items"].get(item_660["question_id"], {}).get("history", []))

        result_880 = app.update_review_feedback(
            app.ReviewFeedbackRequest(
                book_id="workbook_880",
                question_id=item_880["question_id"],
                outcome="pass",
                error_level=None,
                note="880 integration test",
            )
        )
        result_660 = app.update_review_feedback(
            app.ReviewFeedbackRequest(
                book_id="workbook_660",
                question_id=item_660["question_id"],
                outcome="pass",
                error_level=None,
                note="660 integration test",
            )
        )

        state_after = app.load_review_state()
        self.assertEqual(state_after["items"][item_880["question_id"]]["book_id"], "workbook_880")
        self.assertEqual(
            len(state_after["items"][item_660["question_id"]]["history"]),
            history_660_before + 1,
        )

        schedule_after = app.load_review_schedule()
        scheduled = app.scheduled_keys(schedule_after)
        self.assertIn(
            app.schedule_key("workbook_880", item_880["question_id"]),
            scheduled,
        )
        self.assertIn(
            app.schedule_key("workbook_660", item_660["question_id"]),
            scheduled,
        )
        self.assertEqual(result_880["book_id"], "workbook_880")
        self.assertEqual(result_660["book_id"], "workbook_660")

        history = app.flatten_review_history(state_after, limit=500)
        history_880 = next(
            event
            for event in history
            if event["book_id"] == "workbook_880" and event["question_id"] == item_880["question_id"]
        )
        self.assertEqual(
            [history_880["section"], history_880["question_type"], history_880["display_id"]],
            [record_880["section"], record_880["question_type"], record_880["display_id"]],
        )

    def test_today_history_excludes_earlier_events_but_keeps_total(self):
        record = next(
            record
            for record in app.load_book_record("workbook_660")["history"]
            if record.get("error_level")
        )
        today = date.today()
        yesterday = today - timedelta(days=1)
        state = app.default_review_state()
        state["items"] = {
            record["question_id"]: {
                "book_id": "workbook_660",
                "history": [
                    {
                        "reviewed_at": f"{yesterday.isoformat()}T09:00:00",
                        "outcome": "wrong",
                        "error_level": "B",
                    },
                    {
                        "reviewed_at": f"{today.isoformat()}T09:00:00",
                        "outcome": "pass",
                        "error_level": None,
                    },
                ],
            }
        }

        history = app.flatten_review_history(state, limit=None, target_date=today)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["event_index"], 1)
        self.assertEqual(history[0]["review_count"], 2)
        self.assertEqual(app.count_review_events(state), 2)

    def test_deleted_overdue_state_is_not_reinserted(self):
        record = next(
            record
            for record in app.load_book_record("workbook_660")["history"]
            if record.get("error_level")
        )
        question_id = record["question_id"]
        key = app.schedule_key("workbook_660", question_id)
        state = app.load_review_state()
        item = state.setdefault("items", {}).setdefault(question_id, {"history": []})
        item["book_id"] = "workbook_660"
        item["next_due_at"] = (date.today() - timedelta(days=3)).isoformat()
        app.save_review_state(state)

        schedule = app.load_review_schedule()
        app.remove_schedule_key(schedule, key)
        app.save_review_schedule(schedule)

        refreshed = app.ensure_review_schedule(app.load_reviewable_book_records(), state, date.today())
        self.assertNotIn(key, app.scheduled_keys(refreshed))

    def test_overdue_bucket_is_deleted_instead_of_rolled_forward(self):
        today = date.today()
        old_key = "workbook_660:660-overdue"
        today_key = "workbook_660:660-today"
        schedule = {
            "buckets": {
                (today - timedelta(days=1)).isoformat(): [old_key],
                today.isoformat(): [today_key],
            }
        }

        changed = app.discard_overdue_buckets(schedule, today)

        self.assertTrue(changed)
        self.assertNotIn((today - timedelta(days=1)).isoformat(), schedule["buckets"])
        self.assertEqual(schedule["buckets"][today.isoformat()], [today_key])
        self.assertNotIn(old_key, schedule["buckets"][today.isoformat()])


if __name__ == "__main__":
    unittest.main()
