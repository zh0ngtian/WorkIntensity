import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import storage
import token_usage


def _token_count_line(timestamp, total_tokens):
    return json.dumps(
        {
            "type": "event_msg",
            "timestamp": timestamp,
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "total_tokens": total_tokens,
                    }
                },
            },
        }
    )


def _bucket(timestamp):
    local_time = datetime.fromisoformat(timestamp[:-1] + "+00:00").astimezone()
    return local_time.strftime("%Y-%m-%d"), local_time.hour


class TokenUsageAggregationTest(unittest.TestCase):
    def test_aggregate_hourly_usage_from_codex_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "sessions" / "session.jsonl"
            path.parent.mkdir()
            path.write_text(
                "\n".join(
                    [
                        "{not-json",
                        json.dumps({"type": "event_msg", "timestamp": "2026-05-16T00:00:00Z", "payload": {"type": "user_message"}}),
                        json.dumps({"type": "event_msg", "timestamp": "2026-05-16T00:00:00Z", "payload": {"type": "token_count", "info": None}}),
                        _token_count_line("2026-05-16T00:15:00Z", 100),
                        _token_count_line("2026-05-16T00:20:00Z", 100),
                        _token_count_line("2026-05-16T01:20:00Z", 250),
                        _token_count_line("2026-05-16T23:30:00Z", 300),
                        _token_count_line("2026-05-17T00:30:00Z", 20),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = token_usage.aggregate_hourly_token_usage([root])
            hourly_totals = result["hourly_totals"]

            self.assertEqual(hourly_totals[_bucket("2026-05-16T00:15:00Z")], 100)
            self.assertEqual(hourly_totals[_bucket("2026-05-16T01:20:00Z")], 150)
            self.assertEqual(hourly_totals[_bucket("2026-05-16T23:30:00Z")], 50)
            self.assertEqual(hourly_totals[_bucket("2026-05-17T00:30:00Z")], 20)
            self.assertEqual(sum(hourly_totals.values()), 320)


class StorageTokenUsageCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "codex"
        self.root.mkdir()
        self.log_dir = Path(self.tmp.name) / "log"

        self.old_values = {
            "_LOG_DIR": storage._LOG_DIR,
            "_DB_PATH": storage._DB_PATH,
            "_ICLOUD_ROOT_DIR": storage._ICLOUD_ROOT_DIR,
            "_ICLOUD_BACKUP_DIR": storage._ICLOUD_BACKUP_DIR,
            "_ICLOUD_DB_PATH": storage._ICLOUD_DB_PATH,
            "_LAST_ICLOUD_BACKUP_AT": storage._LAST_ICLOUD_BACKUP_AT,
        }
        if storage._DB_CONN is not None:
            storage._DB_CONN.close()
            storage._DB_CONN = None

        storage._LOG_DIR = str(self.log_dir)
        storage._DB_PATH = str(self.log_dir / "work_intensity.sqlite3")
        storage._ICLOUD_ROOT_DIR = str(Path(self.tmp.name) / "missing-icloud")
        storage._ICLOUD_BACKUP_DIR = str(Path(storage._ICLOUD_ROOT_DIR) / "WorkIntensity")
        storage._ICLOUD_DB_PATH = str(Path(storage._ICLOUD_BACKUP_DIR) / "work_intensity.sqlite3")
        storage._LAST_ICLOUD_BACKUP_AT = 0.0

    def tearDown(self):
        if storage._DB_CONN is not None:
            storage._DB_CONN.close()
            storage._DB_CONN = None
        for name, value in self.old_values.items():
            setattr(storage, name, value)
        self.tmp.cleanup()

    def _write_jsonl(self, totals):
        path = self.root / "session.jsonl"
        path.write_text(
            "\n".join(_token_count_line(f"2026-05-16T0{index}:00:00Z", total) for index, total in enumerate(totals))
            + "\n",
            encoding="utf-8",
        )
        return path

    def test_cache_reuses_same_fingerprint_and_rebuilds_on_change(self):
        self._write_jsonl([100])
        first = storage.get_token_usage_by_date_range("2026-05-16", "2026-05-16", roots=[self.root])
        first_total = sum(next(iter(first.values())))
        self.assertEqual(first_total, 100)

        conn = sqlite3.connect(storage._DB_PATH)
        try:
            conn.execute("UPDATE token_usage_hourly SET total_tokens = 999")
            conn.commit()
        finally:
            conn.close()

        reused = storage.get_token_usage_by_date_range("2026-05-16", "2026-05-16", roots=[self.root])
        reused_total = sum(next(iter(reused.values())))
        self.assertEqual(reused_total, 999)

        self._write_jsonl([100, 250])
        rebuilt = storage.get_token_usage_by_date_range("2026-05-16", "2026-05-16", roots=[self.root])
        rebuilt_total = sum(next(iter(rebuilt.values())))
        self.assertEqual(rebuilt_total, 250)


if __name__ == "__main__":
    unittest.main()
