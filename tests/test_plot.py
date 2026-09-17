import json
import os
import re
import sys
import tempfile
import types
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch


sys.modules.setdefault(
    "chinese_calendar",
    types.SimpleNamespace(is_workday=lambda _day: True),
)

import plot


class OffWorkTimeTest(unittest.TestCase):
    def test_requires_fifteen_minutes_of_distinct_active_blocks(self):
        for seconds in ([], [0], [0] * 100, list(range(0, 24 * 36, 36))):
            with self.subTest(seconds=seconds):
                self.assertIsNone(plot.estimate_off_work_time(seconds, 3600))
        self.assertEqual(
            plot.estimate_off_work_time(list(range(0, 25 * 36, 36)), 3600),
            {"time": "05:14", "provisional": False},
        )

    def test_uses_a_sliding_thirty_minute_window(self):
        # Fifteen active minutes spread over nearly thirty minutes qualify.
        seconds = list(range(18 * 60, 18 * 60 + 25 * 72, 72))
        self.assertEqual(
            plot.estimate_off_work_time(seconds, 7200),
            {"time": "05:46", "provisional": False},
        )
        # The oldest block cannot count once it falls outside the window.
        self.assertIsNone(plot.estimate_off_work_time([0] + list(range(972, 1801, 36)), 7200))
        self.assertIsNone(plot.estimate_off_work_time(list(range(0, 25 * 180, 180)), 7200))

    def test_late_clicks_do_not_move_off_work_time_or_restart_confirmation(self):
        work_end = 14 * 3600
        seconds = list(range(work_end - 3600, work_end + 1, 36))
        seconds += [18 * 3600, 18 * 3600 + 36]
        self.assertEqual(
            plot.estimate_off_work_time(list(reversed(seconds)) + seconds, 18 * 3600 + 60),
            {"time": "19:00", "provisional": False},
        )

    def test_later_sustained_work_replaces_previous_end(self):
        seconds = list(range(13 * 3600, 14 * 3600 + 1, 36))
        seconds += list(range(17 * 3600, 18 * 3600 + 1, 36))
        self.assertEqual(
            plot.estimate_off_work_time(seconds, 18 * 3600 + 60),
            {"time": "23:00", "provisional": True},
        )

    def test_confirmation_waits_thirty_minutes_after_the_last_block(self):
        seconds = list(range(0, 900, 36))
        for elapsed, provisional in [(899, True), (2699, True), (2700, False)]:
            with self.subTest(elapsed=elapsed):
                self.assertEqual(
                    plot.estimate_off_work_time(seconds, elapsed),
                    {"time": "05:14", "provisional": provisional},
                )

    def test_off_work_time_uses_five_am_reporting_day(self):
        cases = [
            (18 * 3600 + 59 * 60 + 24, "23:59"),
            (19 * 3600, "次日 00:00"),
            (21 * 3600 + 30 * 60, "次日 02:30"),
            (24 * 3600 - 36, "次日 04:59"),
        ]
        for end, expected in cases:
            with self.subTest(end=end):
                seconds = list(range(end - 24 * 36, end + 1, 36))
                self.assertEqual(
                    plot.estimate_off_work_time(seconds, 24 * 3600 + 1800),
                    {"time": expected, "provisional": False},
                )


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

    def test_recent_week_average_tokens_includes_zero_usage_days(self):
        values = [999, 100, 0, 200, 300, 0, 400, 1200]

        self.assertEqual(plot.calculate_recent_average_token_usage(values), 314)

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
        today_date = date(2026, 6, 1)
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

            _labels, _work_hours, _seconds_map, token_daily, token_map, project_token_map = plot.get_last_several_days_activities(3, today_date)

            start_day = today_date - timedelta(days=2)
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

    def test_rendered_plot_changes_reporting_week_at_five(self):
        for now, expected_day, expected_hour, expected_weekday in [
            (datetime(2026, 6, 1, 4, 59, 59), date(2026, 5, 31), 23, 6),
            (datetime(2026, 6, 1, 5), date(2026, 6, 1), 0, 0),
        ]:
            with self.subTest(now=now), tempfile.TemporaryDirectory() as tmp, patch.object(
                plot, "datetime"
            ) as clock, patch.object(plot, "storage") as storage, patch.object(plot, "serve_plot_html") as serve:
                clock.now.return_value = now
                morning_seconds = list(range(0, 3600, 36))
                storage.get_activity_seconds_for_date.side_effect = lambda day: (
                    [] if day == expected_day and now.hour == 5 else morning_seconds
                )
                storage.get_token_usage_by_date_range.return_value = {str(expected_day): [600] * 24}
                storage.get_token_project_usage_by_date_range.return_value = {
                    str(expected_day): [{"project": "sample", "tokens": 14400}],
                }
                storage.get_token_scale_strength.return_value = 0
                storage.get_token_display_range.return_value = (0, 100)
                storage.get_icloud_backup_time.return_value = None
                old_cwd = os.getcwd()
                try:
                    os.chdir(tmp)
                    plot.plot_fig()
                finally:
                    os.chdir(old_cwd)
                html = (Path(tmp) / "log" / "work_intensity.html").read_text(encoding="utf-8")

                clock.now.assert_called_once_with()
                self.assertIn(f'const currentReportingDateStr = "{expected_day}";', html)
                self.assertIn(f"const currentReportingHour = {expected_hour};", html)
                self.assertIn("const dayStartHour = 5;", html)
                self.assertNotRegex(html, r"__[A-Z_]+__")
                heatmap = json.loads(re.search(r"const heatmapData = (.+)\.map", html).group(1))
                self.assertEqual(len(heatmap), 23 * 7 + expected_weekday + 1)
                expected_hours = 0 if now.hour == 5 else 1.0
                self.assertEqual(heatmap[-1][0:3], [23, expected_weekday, expected_hours])
                self.assertEqual(heatmap[-1][4], str(expected_day))
                self.assertEqual(heatmap[-1][6:9], [14400, [600] * 24, [{"project": "sample", "tokens": 14400}]])
                confirmed = {"time": "05:59", "provisional": False}
                expected_off_work = None if now.hour == 5 else confirmed
                self.assertEqual(heatmap[-1][9], expected_off_work)
                off_work_values = json.loads(re.search(r"const trendOffWorkValues = (.+);", html).group(1))
                self.assertEqual(off_work_values, [confirmed] * 83 + [expected_off_work])
                serve.assert_called_once_with(html)

    def test_rendered_off_work_confirmation_crosses_the_reporting_day_boundary(self):
        for now, provisional in [
            (datetime(2026, 9, 17, 5), True),
            (datetime(2026, 9, 17, 5, 29, 59), True),
            (datetime(2026, 9, 17, 5, 30), False),
        ]:
            today = now.date()
            yesterday = today - timedelta(days=1)
            day_before = today - timedelta(days=2)
            activity = {
                day_before: list(range(13 * 3600, 14 * 3600 + 1, 36)) + [18 * 3600],
                yesterday: list(range(23 * 3600, 24 * 3600, 36)),
                today: [0],
            }
            with self.subTest(now=now), tempfile.TemporaryDirectory() as tmp, patch.object(
                plot, "datetime"
            ) as clock, patch.object(plot, "storage") as storage, patch.object(plot, "serve_plot_html") as serve:
                clock.now.return_value = now
                storage.get_activity_seconds_for_date.side_effect = lambda day: activity.get(day, [])
                storage.get_token_usage_by_date_range.return_value = {}
                storage.get_token_project_usage_by_date_range.return_value = {}
                storage.get_token_scale_strength.return_value = 0
                storage.get_token_display_range.return_value = (0, 100)
                storage.get_icloud_backup_time.return_value = None
                old_cwd = os.getcwd()
                try:
                    os.chdir(tmp)
                    plot.plot_fig()
                finally:
                    os.chdir(old_cwd)
                html = serve.call_args.args[0]
                self.assertNotRegex(html, r"__[A-Z_]+__")
                heatmap = json.loads(re.search(r"const heatmapData = (.+)\.map", html).group(1))
                off_work_values = json.loads(re.search(r"const trendOffWorkValues = (.+);", html).group(1))
                expected = [
                    {"time": "19:00", "provisional": False},
                    {"time": "次日 04:59", "provisional": provisional},
                    None,
                ]
                self.assertEqual([day[9] for day in heatmap[-3:]], expected)
                self.assertEqual(off_work_values[-3:], expected)
                self.assertTrue(all(value is None for value in off_work_values[:-3]))


if __name__ == "__main__":
    unittest.main()
