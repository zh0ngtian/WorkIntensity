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

    def test_token_metric_values_use_workday_nonzero_average_and_today(self):
        start_day = datetime(2026, 5, 11).date()
        displayed_dates = [start_day + timedelta(days=index) for index in range(4)]

        average, peak, today = plot.calculate_token_metric_values(displayed_dates, [0, 1000, 500, 3000])

        self.assertEqual(average, 1500)
        self.assertEqual(peak, 3000)
        self.assertEqual(today, 3000)

    def test_format_token_count_uses_compact_units(self):
        self.assertEqual(plot.format_token_count(999), "999")
        self.assertEqual(plot.format_token_count(1200), "1.2K")
        self.assertEqual(plot.format_token_count(2_500_000), "2.5M")

    def test_token_axis_scale_stays_linear_when_values_are_comparable(self):
        scale = plot.build_token_axis_scale([0, 20, 40, 60, 80, 100])

        self.assertEqual(scale["maxValue"], 100)
        self.assertEqual(scale["minValue"], 0)
        self.assertEqual(scale["segmentCount"], 5)
        self.assertEqual(scale["axisMax"], 5)
        self.assertEqual(scale["compression"], 0)
        self.assertEqual(scale["values"], [0, 1, 2, 3, 4, 5])

    def test_token_axis_scale_keeps_endpoints_fixed_and_compresses_larger_values_more(self):
        linear = plot.build_token_axis_scale([0, 25, 50, 75, 100], compression=0)
        compressed = plot.build_token_axis_scale([0, 25, 50, 75, 100], compression=1)

        self.assertEqual(compressed["values"][0], linear["values"][0])
        self.assertEqual(compressed["values"][-1], linear["values"][-1])
        self.assertGreater(
            compressed["values"][1] - compressed["values"][0],
            compressed["values"][-1] - compressed["values"][-2],
        )

    def test_token_axis_scale_maps_equal_values_to_the_same_height(self):
        scale = plot.build_token_axis_scale([0, 10, 10, 1000], compression=1)

        self.assertEqual(scale["values"][1], scale["values"][2])

    def test_token_axis_scale_handles_all_zero_values(self):
        scale = plot.build_token_axis_scale([0, None, 0])

        self.assertEqual(scale["values"], [0, 0, 0])
        self.assertEqual(scale["maxValue"], 0)
        self.assertEqual(scale["minValue"], 0)
        self.assertEqual(scale["axisMax"], 1)

    def test_format_icloud_backup_time(self):
        self.assertEqual(plot.format_icloud_backup_time(None), "未备份")
        self.assertEqual(plot.format_icloud_backup_time(datetime(2026, 6, 1, 14, 5)), "2026-06-01 14:05")

    def test_last_several_days_token_totals_match_hourly_arrays(self):
        old_get_token_usage = plot.storage.get_token_usage_by_date_range
        old_get_project_usage = plot.storage.get_token_project_usage_by_date_range
        old_get_activity = plot.storage.get_activity_seconds_for_date
        project_refresh_values = []

        def fake_get_token_usage(start_day, end_day):
            usage = {}
            current_day = start_day
            while current_day <= end_day:
                usage[current_day.strftime("%Y-%m-%d")] = [current_day.day for _ in range(24)]
                current_day = current_day + timedelta(days=1)
            return usage

        def fake_get_project_usage(start_day, end_day, refresh=True):
            project_refresh_values.append(refresh)
            usage = {}
            current_day = start_day
            while current_day <= end_day:
                usage[current_day.strftime("%Y-%m-%d")] = [
                    {
                        "project": "project-a",
                        "tokens": current_day.day,
                    }
                ]
                current_day = current_day + timedelta(days=1)
            return usage

        try:
            plot.storage.get_token_usage_by_date_range = fake_get_token_usage
            plot.storage.get_token_project_usage_by_date_range = fake_get_project_usage
            plot.storage.get_activity_seconds_for_date = lambda _day: []

            _labels, _work_hours, _seconds_map, token_daily, token_map, project_token_map = plot.get_last_several_days_activities(3)

            start_day = datetime.now().date() - timedelta(days=2)
            expected = []
            for index in range(3):
                day = start_day + timedelta(days=index)
                day_key = day.strftime("%Y-%m-%d")
                self.assertEqual(token_daily[index], sum(token_map[day_key]))
                self.assertEqual(project_token_map[day_key][0]["tokens"], day.day)
                expected.append(day.day * 24)
            self.assertEqual(token_daily, expected)
            self.assertEqual(project_refresh_values, [False])
        finally:
            plot.storage.get_token_usage_by_date_range = old_get_token_usage
            plot.storage.get_token_project_usage_by_date_range = old_get_project_usage
            plot.storage.get_activity_seconds_for_date = old_get_activity

    def test_trend_slice_uses_recorded_days_for_work_and_tokens(self):
        values = [10, 20, 30, 40, 0, 0]
        self.assertEqual(plot.slice_recent_trend_values(values, num_days=4, trend_days=3), [20, 30, 40])


if __name__ == "__main__":
    unittest.main()
