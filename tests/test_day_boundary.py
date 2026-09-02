import unittest
from datetime import date, datetime

from day_boundary import reporting_date, reporting_hour


class ReportingDayTest(unittest.TestCase):
    def test_local_day_changes_at_five_including_month_and_year_boundaries(self):
        cases = [
            (datetime(2026, 9, 2, 0), date(2026, 9, 1), 19),
            (datetime(2026, 9, 2, 4, 59, 59), date(2026, 9, 1), 23),
            (datetime(2026, 9, 2, 5), date(2026, 9, 2), 0),
            (datetime(2026, 9, 2, 23, 59, 59), date(2026, 9, 2), 18),
            (datetime(2026, 6, 1, 4), date(2026, 5, 31), 23),
            (datetime(2026, 1, 1, 4), date(2025, 12, 31), 23),
        ]
        for now, expected_date, expected_hour in cases:
            with self.subTest(now=now):
                self.assertEqual(reporting_date(now), expected_date)
                self.assertEqual(reporting_hour(now), expected_hour)


if __name__ == "__main__":
    unittest.main()
