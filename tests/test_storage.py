import sqlite3
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


class ICloudSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.log_dir = self.root / "log"
        self.cloud_root = self.root / "icloud"
        self.cloud_root.mkdir()
        self.backup_dir = self.cloud_root / "WorkIntensity"
        self.backup_path = self.backup_dir / "work_intensity.sqlite3"
        patches = patch.multiple(
            storage,
            _LOG_DIR=str(self.log_dir),
            _DB_PATH=str(self.log_dir / "work_intensity.sqlite3"),
            _ICLOUD_ROOT_DIR=str(self.cloud_root),
            _ICLOUD_BACKUP_DIR=str(self.backup_dir),
            _ICLOUD_DB_PATH=str(self.backup_path),
            _DB_CONN=None,
            _LAST_ICLOUD_BACKUP_AT=0.0,
        )
        patches.start()
        self.addCleanup(patches.stop)
        self.addCleanup(self.close_connection)

    def close_connection(self):
        if storage._DB_CONN is not None:
            storage._DB_CONN.close()
            storage._DB_CONN = None

    def create_backup(self):
        self.backup_dir.mkdir()
        with sqlite3.connect(self.backup_path) as conn:
            storage._ensure_tables(conn)
            conn.execute("INSERT INTO activity_blocks VALUES ('2026-06-01', 500)")

    def backup_rows(self):
        with sqlite3.connect(self.backup_path) as conn:
            return conn.execute("SELECT day, block_index FROM activity_blocks ORDER BY day, block_index").fetchall()

    def test_default_disabled_sync_does_not_create_cloud_backup(self):
        storage.record_activity(datetime(2026, 6, 2, 5))
        self.assertFalse(storage.sync_to_icloud(force=True))
        self.assertFalse(self.backup_dir.exists())
        self.assertEqual(storage._LAST_ICLOUD_BACKUP_AT, 0.0)

    def test_disabled_sync_does_not_restore_or_modify_existing_backup(self):
        self.create_backup()
        original_backup = self.backup_path.read_bytes()
        storage.record_activity(datetime(2026, 6, 2, 5))
        self.assertFalse(storage.sync_to_icloud(force=True))
        self.assertEqual(storage.get_connection().execute("SELECT * FROM activity_blocks").fetchall(), [
            ("2026-06-02", 500),
        ])
        self.assertEqual(self.backup_path.read_bytes(), original_backup)

    def test_enabled_sync_backs_up_and_preserves_interval_and_force_behavior(self):
        storage.set_icloud_sync_enabled(True)
        with patch.object(storage.time, "monotonic", return_value=10000):
            storage.record_activity(datetime(2026, 6, 2, 5))
            self.assertEqual(self.backup_rows(), [("2026-06-02", 500)])
            storage.record_activity(datetime(2026, 6, 2, 6))
            self.assertEqual(self.backup_rows(), [("2026-06-02", 500)])
            self.assertTrue(storage.sync_to_icloud(force=True))
            self.assertEqual(self.backup_rows(), [("2026-06-02", 500), ("2026-06-02", 600)])

    def test_disabling_sync_stops_automatic_and_forced_backups(self):
        storage.set_icloud_sync_enabled(True)
        storage.record_activity(datetime(2026, 6, 2, 5))
        self.assertTrue(storage.sync_to_icloud(force=True))
        original_backup = self.backup_path.read_bytes()
        storage.set_icloud_sync_enabled(False)
        with patch.object(storage.time, "monotonic", return_value=storage._LAST_ICLOUD_BACKUP_AT + 3601):
            storage.record_activity(datetime(2026, 6, 2, 6))
            self.assertFalse(storage.sync_to_icloud(force=True))
        self.assertEqual(self.backup_path.read_bytes(), original_backup)

    def test_enabled_sync_restores_backup_before_opening_missing_local_database(self):
        self.create_backup()
        storage.set_icloud_sync_enabled(True)
        self.assertEqual(storage.get_connection().execute("SELECT * FROM activity_blocks").fetchall(), [
            ("2026-06-01", 500),
        ])

    def test_enabled_sync_preserves_existing_local_database(self):
        storage.record_activity(datetime(2026, 6, 2, 5))
        self.close_connection()
        self.create_backup()
        storage.set_icloud_sync_enabled(True)
        self.assertEqual(storage.get_connection().execute("SELECT * FROM activity_blocks").fetchall(), [
            ("2026-06-02", 500),
        ])


if __name__ == "__main__":
    unittest.main()
