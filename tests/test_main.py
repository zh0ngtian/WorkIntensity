import json
import subprocess
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import main


class CopyCredentialsTest(unittest.TestCase):
    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.path = Path(temporary_directory.name) / "tos-credentials.json"
        path_patch = patch.object(main, "_TOS_CREDENTIALS_PATH", self.path)
        path_patch.start()
        self.addCleanup(path_patch.stop)

    def test_copies_export_command_and_reads_latest_credentials(self):
        with patch("main.subprocess.run") as copy:
            for token in ["zzz", "updated"]:
                self.path.write_text(json.dumps({"AK": "xxx", "SK": "yyy", "TOKEN": token}), encoding="utf-8")
                main._copy_tos_credentials()
                copy.assert_called_with(
                    ["pbcopy"],
                    input=f'export AK="xxx" && export SK="yyy" && export TOKEN="{token}"',
                    text=True,
                    check=True,
                )

    def test_export_command_preserves_shell_special_characters(self):
        credentials = {"AK": 'a"b\\c', "SK": "$(printf expanded)`printf expanded`$HOME", "TOKEN": "x'y\nz+/="}
        self.path.write_text(json.dumps(credentials), encoding="utf-8")
        with patch("main.subprocess.run") as copy:
            main._copy_tos_credentials()
            command = copy.call_args.kwargs["input"]
        for shell in ["/bin/sh", "/bin/zsh"]:
            with self.subTest(shell=shell):
                result = subprocess.run(
                    [shell, "-c", command + ''' && printf '%s\\0' "$AK" "$SK" "$TOKEN"'''],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertEqual(result.stdout.split("\0"), [*credentials.values(), ""])

    def test_copies_errors_for_missing_file_or_invalid_credentials(self):
        invalid_contents = [
            "{", "[]", "{}",
            json.dumps({"AK": "xxx", "SK": "yyy"}),
            json.dumps({"AK": "xxx", "SK": "yyy", "TOKEN": ""}),
            json.dumps({"AK": "xxx", "SK": "yyy", "TOKEN": 123}),
        ]
        with patch("main.subprocess.run") as copy:
            main._copy_tos_credentials()
            self.assertIn("FileNotFoundError", copy.call_args.kwargs["input"])
            for content in invalid_contents:
                with self.subTest(content=content):
                    self.path.write_text(content, encoding="utf-8")
                    main._copy_tos_credentials()
                    self.assertTrue(copy.call_args.kwargs["input"].startswith("复制凭证失败："))
                    self.assertIn("Error:", copy.call_args.kwargs["input"])

    def test_retries_copying_clipboard_error(self):
        self.path.write_text(json.dumps({"AK": "xxx", "SK": "yyy", "TOKEN": "zzz"}), encoding="utf-8")
        with patch("main.subprocess.run", side_effect=[OSError("clipboard unavailable"), None]) as copy:
            main._copy_tos_credentials()
            self.assertEqual(copy.call_count, 2)
            copy.assert_called_with(
                ["pbcopy"],
                input="复制凭证失败：OSError: clipboard unavailable",
                text=True,
                check=True,
            )


class StatusTitleTest(unittest.TestCase):
    def test_status_title_switches_at_five_and_quota_receives_real_time(self):
        for now, expected_day in [
            (datetime(2026, 1, 1, 4, 59, 59), date(2025, 12, 31)),
            (datetime(2026, 1, 1, 5), date(2026, 1, 1)),
        ]:
            with self.subTest(now=now):
                storage = Mock()
                storage.get_activity_seconds_for_date.return_value = list(range(100))
                storage.get_token_usage_by_date_range.return_value = {str(expected_day): [250]}
                quota = Mock(return_value="82% · 7d12h")

                self.assertEqual(main._build_status_title(now, storage, str, quota), "1.0h · 250 · 82% · 7d12h")
                storage.get_activity_seconds_for_date.assert_called_once_with(expected_day)
                storage.get_token_usage_by_date_range.assert_called_once_with(expected_day, expected_day)
                quota.assert_called_once_with(now)

    def test_status_title_shows_today_work_hours_and_tokens(self):
        now = datetime(2026, 7, 26, 14, 30)

        class Storage:
            @staticmethod
            def get_activity_seconds_for_date(_value):
                return list(range(325))

            @staticmethod
            def get_token_usage_by_date_range(_start, _end):
                return {"2026-07-26": [500, 700]}

        title = main._build_status_title(
            now,
            Storage,
            lambda value: f"{value / 1000:.1f}K",
            lambda _now: "82% · 7d12h",
        )

        self.assertEqual(title, "3.2h · 1.2K · 82% · 7d12h")

    def test_status_title_keeps_available_metric_when_the_other_fails(self):
        now = datetime(2026, 7, 26, 14, 30)

        class ActivityUnavailableStorage:
            @staticmethod
            def get_activity_seconds_for_date(_value):
                raise RuntimeError("activity unavailable")

            @staticmethod
            def get_token_usage_by_date_range(_start, _end):
                return {"2026-07-26": [250]}

        class TokenUnavailableStorage:
            @staticmethod
            def get_activity_seconds_for_date(_value):
                return list(range(150))

            @staticmethod
            def get_token_usage_by_date_range(_start, _end):
                raise RuntimeError("token usage unavailable")

        self.assertEqual(
            main._build_status_title(now, ActivityUnavailableStorage, str, lambda _now: "82% · 7d12h"),
            "--h · 250 · 82% · 7d12h",
        )
        self.assertEqual(
            main._build_status_title(now, TokenUnavailableStorage, str, lambda _now: "82% · 7d12h"),
            "1.5h · -- · 82% · 7d12h",
        )

    def test_status_title_keeps_local_metrics_when_quota_fails(self):
        now = datetime(2026, 7, 26, 14, 30)

        class Storage:
            @staticmethod
            def get_activity_seconds_for_date(_value):
                return list(range(150))

            @staticmethod
            def get_token_usage_by_date_range(_start, _end):
                return {"2026-07-26": [250]}

        def quota_unavailable(_now):
            raise RuntimeError("quota unavailable")

        self.assertEqual(
            main._build_status_title(now, Storage, str, quota_unavailable),
            "1.5h · 250 · --% · --",
        )


if __name__ == "__main__":
    unittest.main()
