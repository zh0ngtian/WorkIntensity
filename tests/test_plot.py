import sys
import types
import unittest
from datetime import datetime, timedelta


sys.modules.setdefault(
    "chinese_calendar",
    types.SimpleNamespace(is_workday=lambda _day: True),
)

import plot


class PlotTokenDataTest(unittest.TestCase):
    def test_daily_token_usage_is_sum_of_hourly_values(self):
        self.assertEqual(plot.calculate_daily_token_usage([1, 2, 3] + [0 for _ in range(21)]), 6)

    def test_last_several_days_token_totals_match_hourly_arrays(self):
        old_get_token_usage = plot.storage.get_token_usage_by_date_range
        old_get_activity = plot.storage.get_activity_seconds_for_date

        def fake_get_token_usage(start_day, end_day):
            usage = {}
            current_day = start_day
            while current_day <= end_day:
                usage[current_day.strftime("%Y-%m-%d")] = [current_day.day for _ in range(24)]
                current_day = current_day + timedelta(days=1)
            return usage

        try:
            plot.storage.get_token_usage_by_date_range = fake_get_token_usage
            plot.storage.get_activity_seconds_for_date = lambda _day: []

            _labels, _work_hours, _seconds_map, token_daily, token_map = plot.get_last_several_days_activities(3)

            start_day = datetime.now().date() - timedelta(days=2)
            expected = []
            for index in range(3):
                day = start_day + timedelta(days=index)
                day_key = day.strftime("%Y-%m-%d")
                self.assertEqual(token_daily[index], sum(token_map[day_key]))
                expected.append(day.day * 24)
            self.assertEqual(token_daily, expected)
        finally:
            plot.storage.get_token_usage_by_date_range = old_get_token_usage
            plot.storage.get_activity_seconds_for_date = old_get_activity

    def test_trend_slice_uses_recorded_days_for_work_and_tokens(self):
        values = [10, 20, 30, 40, 0, 0]
        self.assertEqual(plot.slice_recent_trend_values(values, num_days=4, trend_days=3), [20, 30, 40])


if __name__ == "__main__":
    unittest.main()
