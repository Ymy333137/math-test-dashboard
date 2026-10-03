import subprocess
import unittest
from unittest.mock import patch

import app


class GitPullTests(unittest.TestCase):
    def test_manual_pull_works_when_auto_sync_disabled(self):
        with patch.object(app, "AUTO_SYNC_RECORDS", False), patch.object(
            app, "records_dirty_files", return_value=[" M review_state.json"]
        ), patch.object(app, "git_command") as git:
            self.assertEqual(app.sync_records_repo()["status"], "disabled")
            self.assertEqual(app.sync_records_repo(manual=True)["status"], "dirty")
            git.assert_not_called()

    def test_fast_forward_pull(self):
        responses = [
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "0 2", ""),
            subprocess.CompletedProcess([], 0, "", ""),
        ]
        with patch.object(app, "records_dirty_files", return_value=[]), patch.object(
            app, "git_command", side_effect=responses
        ) as git:
            self.assertEqual(app.sync_records_repo(manual=True)["status"], "pulled")
            self.assertEqual(git.call_args.args[0], ["pull", "--ff-only"])

    def test_diverged_does_not_pull(self):
        responses = [
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "1 2", ""),
        ]
        with patch.object(app, "records_dirty_files", return_value=[]), patch.object(
            app, "git_command", side_effect=responses
        ) as git:
            self.assertEqual(app.sync_records_repo(manual=True)["status"], "diverged")
            self.assertEqual(git.call_count, 2)

    def test_failed_sync_does_not_reload_data(self):
        with patch.object(app, "sync_records_repo", return_value={"status": "error"}), patch.object(
            app, "build_dashboard_payload"
        ) as dashboard:
            self.assertFalse(app.pull_records_payload()["ok"])
            dashboard.assert_not_called()

    def test_success_does_not_fetch_twice(self):
        result = {"status": "up_to_date"}
        with patch.object(app, "sync_records_repo", return_value=result) as sync, patch.object(
            app, "build_dashboard_payload", return_value={"books": []}
        ) as dashboard:
            self.assertTrue(app.pull_records_payload()["ok"])
            sync.assert_called_once_with(manual=True)
            dashboard.assert_called_once_with(result)
