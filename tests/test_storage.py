import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import plot
import storage


class ActivityReportingDayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patches = patch.multiple(
            storage,
            _LOG_DIR=str(self.root),
            _DB_PATH=str(self.root / "activity.sqlite3"),
            _ICLOUD_ROOT_DIR=str(self.root / "missing-icloud"),
            _ICLOUD_DB_PATH=str(self.root / "missing-backup.sqlite3"),
            _DB_CONN=None,
        )
        patches.start()
        self.addCleanup(patches.stop)
        self.addCleanup(self.close_connection)

    def close_connection(self):
        if storage._DB_CONN is not None:
            storage._DB_CONN.close()

    def test_recording_keeps_calendar_dates_and_queries_join_at_five(self):
        for now in [
            datetime(2025, 12, 31, 4, 59, 59),
            datetime(2025, 12, 31, 5),
            datetime(2025, 12, 31, 23, 59, 59),
            datetime(2026, 1, 1, 0),
            datetime(2026, 1, 1, 4, 59, 59),
            datetime(2026, 1, 1, 5),
            datetime(2026, 1, 1, 5, 0, 1),
        ]:
            storage.record_activity(now)

        rows = storage.get_connection().execute(
            "SELECT day, block_index FROM activity_blocks ORDER BY day, block_index"
        ).fetchall()
        self.assertEqual(rows, [
            ("2025-12-31", 499), ("2025-12-31", 500), ("2025-12-31", 2399),
            ("2026-01-01", 0), ("2026-01-01", 499), ("2026-01-01", 500),
        ])
        expected = [0, 19 * 3600 - 36, 19 * 3600, 24 * 3600 - 36]
        for value in ["2025-12-31", date(2025, 12, 31), datetime(2026, 1, 1, 4, 59, 59)]:
            with self.subTest(value=value):
                self.assertEqual(storage.get_activity_seconds_for_date(value), expected)
        self.assertEqual(storage.get_activity_seconds_for_date(datetime(2026, 1, 1, 5)), [0])
        hourly = plot.calculate_hourly_percent(expected)
        self.assertEqual([hourly[index] for index in (0, 18, 19, 23)], [1, 1, 1, 1])
        self.assertEqual(sum(hourly), 4)

    def test_legacy_logs_from_both_dates_are_imported_without_modification(self):
        logs = {
            "2026-05-31.log": "[04:59:59] input\n[05:00:00] input\n[23:59:59] input\n",
            "2026-06-01.log": "[00:00:00] input\n[04:59:59] input\n[05:00:00] input\n",
        }
        for name, content in logs.items():
            (self.root / name).write_text(content, encoding="utf-8")
        expected = [0, 19 * 3600 - 36, 19 * 3600, 24 * 3600 - 36]

        self.assertEqual(storage.get_activity_seconds_for_date("2026-05-31"), expected)
        self.assertEqual(storage.get_activity_seconds_for_date("2026-05-31"), expected)
        self.assertEqual(storage.get_activity_seconds_for_date("2026-06-01"), [0])
        self.assertEqual(storage.get_connection().execute("SELECT COUNT(*) FROM activity_blocks").fetchone()[0], 6)
        for name, content in logs.items():
            self.assertEqual((self.root / name).read_text(encoding="utf-8"), content)


if __name__ == "__main__":
    unittest.main()
