import unittest
from datetime import datetime

import main


class StatusTitleTest(unittest.TestCase):
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
