import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import app


class Workbook880IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        records_dir = str(app.RECORDS_DIR)
        if records_dir == "/Users/y-mac/Documents/math-test_2/records":
            raise RuntimeError("测试必须使用 records 临时副本")

    def test_dashboard_and_structured_errors(self):
        record_file = app.load_book_record("workbook_880")
        records = app.enriched_history_records(record_file)
        expected_abc = {
            level: sum(1 for record in records if record.get("error_level") == level)
            for level in ["A", "B", "C"]
        }
        expected_error_total = sum(expected_abc.values())

        dashboard = app.build_dashboard_payload()
        book = next(item for item in dashboard["books"] if item["book_id"] == "workbook_880")
        self.assertEqual(book["total"], len(records))
        self.assertEqual(book["abc_counts"], expected_abc)
        self.assertEqual(book["error_total"], expected_error_total)

        errors = app.build_book_errors("workbook_880")
        items = [item for unit in errors["units"] for level in unit["levels"].values() for item in level]
        self.assertEqual(len(items), expected_error_total)
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

    def test_loading_today_preserves_overdue_bucket_for_manual_move(self):
        today = date.today()
        old_key = "workbook_660:660-overdue"
        today_key = "workbook_660:660-today"
        schedule = {
            "buckets": {
                (today - timedelta(days=1)).isoformat(): [old_key],
                today.isoformat(): [today_key],
            }
        }

        with patch("app.load_review_schedule", return_value=schedule):
            refreshed = app.ensure_review_schedule({}, {"settings": {}}, today)

        self.assertEqual(refreshed["buckets"][(today - timedelta(days=1)).isoformat()], [old_key])
        self.assertEqual(refreshed["buckets"][today.isoformat()], [today_key])
        self.assertNotIn(old_key, refreshed["buckets"][today.isoformat()])

    def test_git_summary_exposes_manual_push_command(self):
        output = """
Summary:
  app: 未运行：仅 records 模式
  records: 已提交但 push 失败：请到终端重新 push
"""
        results = app.parse_commit_summary(output)

        self.assertEqual(results["app"]["status"], "skipped")
        self.assertEqual(results["records"]["status"], "push_failed")
        self.assertEqual(
            results["records"]["retry_command"],
            f'git -C "{app.RECORDS_DIR}" push',
        )

    def test_web_git_action_runs_records_only_mode(self):
        process = SimpleNamespace(
            returncode=0,
            stdout="""
Summary:
  app: 未运行：仅 records 模式
  records: 无需 git：没有改动
""",
            stderr="",
        )
        with patch("app.subprocess.run", return_value=process) as run:
            result = app.run_commit_script()

        command = run.call_args.args[0]
        self.assertEqual(
            command,
            [str(app.COMMIT_SCRIPT), "--records-only", app.RECORDS_COMMIT_MESSAGE],
        )
        self.assertEqual(set(result["results"]), {"records"})
        self.assertEqual(result["results"]["records"]["status"], "clean")

    def test_daily_queue_keeps_every_due_item_above_soft_limit(self):
        records = [
            record
            for record in app.load_book_record("workbook_660")["history"]
            if record.get("error_level")
        ][:3]
        today = date.today()
        keys = [app.schedule_key("workbook_660", record["question_id"]) for record in records]
        schedule = app.default_review_schedule()
        schedule["buckets"] = {today.isoformat(): keys.copy()}
        schedule["daily_plans"] = {today.isoformat(): keys.copy()}

        with patch("app.ensure_review_schedule", return_value=schedule):
            payload = app.build_review_payload(daily_limit=1)

        self.assertEqual(len(payload["queue"]), 3)
        self.assertEqual(payload["deferred"], [])
        self.assertEqual(payload["summary"]["overflow_total"], 2)

    def test_backlog_is_a_newest_first_stack_and_reentry_resets_position(self):
        schedule = app.default_review_schedule()
        schedule["buckets"] = {date.today().isoformat(): ["book:q1", "book:q2", "book:q3"]}

        app.add_backlog_keys(schedule, ["book:q1", "book:q2"])
        self.assertEqual(schedule["backlog"], ["book:q1", "book:q2"])

        schedule["buckets"] = {date.today().isoformat(): ["book:q2"]}
        app.add_backlog_keys(schedule, ["book:q2"])
        self.assertEqual(schedule["backlog"], ["book:q2", "book:q1"])
        self.assertNotIn("book:q2", schedule["buckets"].get(date.today().isoformat(), []))

    def test_release_buffer_uses_capacity_then_forces_starved_items(self):
        today = date.today()
        schedule = app.default_review_schedule()
        schedule["buckets"] = {today.isoformat(): [f"book:fixed-{index}" for index in range(19)]}
        schedule["release_buffer"] = {today.isoformat(): ["book:buffer-1", "book:buffer-2"]}

        changed = app.activate_release_buffer(schedule, today, daily_limit=20, max_wait_days=7)

        self.assertTrue(changed)
        self.assertIn("book:buffer-1", schedule["buckets"][today.isoformat()])
        self.assertIn("book:buffer-2", schedule["release_buffer"][today.isoformat()])

        starved_day = today + timedelta(days=7)
        schedule["buckets"] = {starved_day.isoformat(): [f"book:busy-{index}" for index in range(20)]}
        changed = app.activate_release_buffer(schedule, starved_day, daily_limit=20, max_wait_days=7)

        self.assertTrue(changed)
        self.assertIn("book:buffer-2", schedule["buckets"][starved_day.isoformat()])
        self.assertIn("book:buffer-2", schedule["forced_releases"][starved_day.isoformat()])

    def test_terminal_pass_graduates_and_maintenance_failure_reactivates(self):
        record = next(
            record
            for record in app.load_book_record("workbook_660")["history"]
            if record.get("error_level") == "A"
        )
        state = app.default_review_state()
        state["items"] = {
            record["question_id"]: {
                "book_id": "workbook_660",
                "error_level": "A",
                "interval_index": len(state["settings"]["intervals"]["A"]) - 1,
                "history": [],
            }
        }

        with (
            patch("app.load_review_state", return_value=state),
            patch("app.save_review_state"),
            patch("app.sync_schedule_for_question") as sync,
        ):
            result = app.update_review_feedback(
                app.ReviewFeedbackRequest(
                    book_id="workbook_660",
                    question_id=record["question_id"],
                    outcome="pass",
                    queue_source="daily",
                )
            )

            self.assertEqual(result["status"], "graduated")
            self.assertEqual(result["interval_days"], 60)
            self.assertTrue(result["buffered"])
            self.assertEqual(state["items"][record["question_id"]]["status"], "graduated")
            self.assertTrue(sync.call_args.kwargs["buffered"])

            result = app.update_review_feedback(
                app.ReviewFeedbackRequest(
                    book_id="workbook_660",
                    question_id=record["question_id"],
                    outcome="wrong",
                    error_level="B",
                    queue_source="maintenance",
                )
            )

        self.assertEqual(result["status"], "active")
        self.assertEqual(result["interval_days"], 1)
        self.assertFalse(result["buffered"])
        self.assertEqual(state["items"][record["question_id"]]["error_level"], "B")

    def test_daily_review_sort_groups_books_and_pages_descending(self):
        items = [
            {
                "book_id": "workbook_660",
                "question_id": "660-240",
                "page": None,
                "question_number": 240,
                "sort_order": 240,
            },
            {
                "book_id": "workbook_880",
                "question_id": "880-page-10",
                "page": 10,
                "question_number": 10,
                "sort_order": 100,
            },
            {
                "book_id": "workbook_880",
                "question_id": "880-page-20-later",
                "page": 20,
                "question_number": 20,
                "sort_order": 202,
            },
            {
                "book_id": "workbook_660",
                "question_id": "660-120",
                "page": None,
                "question_number": 120,
                "sort_order": 120,
            },
            {
                "book_id": "workbook_880",
                "question_id": "880-page-20-earlier",
                "page": 20,
                "question_number": 20,
                "sort_order": 201,
            },
        ]

        ordered = sorted(items, key=app.daily_review_sort_key)

        self.assertEqual(
            [item["question_id"] for item in ordered],
            [
                "880-page-20-later",
                "880-page-20-earlier",
                "880-page-10",
                "660-240",
                "660-120",
            ],
        )


if __name__ == "__main__":
    unittest.main()
