import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import storage
import token_usage


def _token_count_line(timestamp, total_tokens, last_usage=None, total_usage=None, model=None):
    info = {
        "total_token_usage": total_usage or {
            "total_tokens": total_tokens,
        }
    }
    if "total_tokens" not in info["total_token_usage"]:
        info["total_token_usage"]["total_tokens"] = total_tokens
    if last_usage is not None:
        info["last_token_usage"] = last_usage
    if model is not None:
        info["model"] = model

    return json.dumps(
        {
            "type": "event_msg",
            "timestamp": timestamp,
            "payload": {
                "type": "token_count",
                "info": info,
            },
        }
    )


def _session_meta_line(cwd):
    return json.dumps(
        {
            "type": "session_meta",
            "payload": {
                "cwd": cwd,
            },
        }
    )


def _detailed_token_count_line(timestamp, total_tokens, input_tokens, last_input_tokens):
    return _token_count_line(
        timestamp,
        total_tokens,
        last_usage={
            "input_tokens": last_input_tokens,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "reasoning_output_tokens": 0,
            "total_tokens": last_input_tokens,
        },
        total_usage={
            "input_tokens": input_tokens,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "reasoning_output_tokens": 0,
            "total_tokens": total_tokens,
        },
        model="gpt-5",
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
                        _session_meta_line("/tmp/alpha-project"),
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
            project_daily_totals = result["project_daily_totals"]

            self.assertEqual(hourly_totals[_bucket("2026-05-16T00:15:00Z")], 100)
            self.assertEqual(hourly_totals[_bucket("2026-05-16T01:20:00Z")], 150)
            self.assertEqual(hourly_totals[_bucket("2026-05-16T23:30:00Z")], 50)
            self.assertEqual(hourly_totals[_bucket("2026-05-17T00:30:00Z")], 20)
            self.assertEqual(sum(hourly_totals.values()), 320)
            self.assertEqual(project_daily_totals[(_bucket("2026-05-16T00:15:00Z")[0], "alpha-project")], 250)
            self.assertEqual(project_daily_totals[(_bucket("2026-05-17T00:30:00Z")[0], "alpha-project")], 70)

    def test_aggregate_hourly_usage_skips_invalid_utf8_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "sessions" / "session.jsonl"
            path.parent.mkdir()
            path.write_bytes(
                b"\xa3\n"
                + (_token_count_line("2026-05-16T00:15:00Z", 100) + "\n").encode("utf-8")
            )

            result = token_usage.aggregate_hourly_token_usage([root])
            hourly_totals = result["hourly_totals"]

            self.assertEqual(hourly_totals[_bucket("2026-05-16T00:15:00Z")], 100)
            self.assertEqual(sum(hourly_totals.values()), 100)

    def test_codex_fork_replayed_token_counts_are_deduped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            sessions.mkdir()

            original = sessions / "a-original.jsonl"
            original.write_text(
                "\n".join(
                    [
                        _session_meta_line("/tmp/original-project"),
                        _detailed_token_count_line("2026-05-16T00:00:00Z", 100, 100, 100),
                        _detailed_token_count_line("2026-05-16T01:00:00Z", 250, 250, 150),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            fork = sessions / "z-fork.jsonl"
            fork.write_text(
                "\n".join(
                    [
                        _session_meta_line("/tmp/fork-project"),
                        _detailed_token_count_line("2026-05-17T02:00:00Z", 100, 100, 100),
                        _detailed_token_count_line("2026-05-17T02:10:00Z", 250, 250, 150),
                        _detailed_token_count_line("2026-05-17T03:00:00Z", 400, 400, 150),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = token_usage.aggregate_hourly_token_usage([root])
            hourly_totals = result["hourly_totals"]
            project_daily_totals = result["project_daily_totals"]

            self.assertEqual(hourly_totals[_bucket("2026-05-16T00:00:00Z")], 100)
            self.assertEqual(hourly_totals[_bucket("2026-05-16T01:00:00Z")], 150)
            self.assertEqual(hourly_totals[_bucket("2026-05-17T03:00:00Z")], 150)
            self.assertNotIn(_bucket("2026-05-17T02:00:00Z"), hourly_totals)
            self.assertEqual(sum(hourly_totals.values()), 400)
            self.assertEqual(project_daily_totals[(_bucket("2026-05-16T00:00:00Z")[0], "original-project")], 250)
            self.assertEqual(project_daily_totals[(_bucket("2026-05-17T03:00:00Z")[0], "fork-project")], 150)

    def test_codex_fork_dedupe_keeps_earliest_timestamp_when_replay_sorts_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            sessions.mkdir()

            replay = sessions / "a-replay.jsonl"
            replay.write_text(
                _detailed_token_count_line("2026-05-17T02:00:00Z", 100, 100, 100) + "\n",
                encoding="utf-8",
            )

            original = sessions / "z-original.jsonl"
            original.write_text(
                _detailed_token_count_line("2026-05-16T00:00:00Z", 100, 100, 100) + "\n",
                encoding="utf-8",
            )

            result = token_usage.aggregate_hourly_token_usage([root])
            hourly_totals = result["hourly_totals"]

            self.assertEqual(hourly_totals[_bucket("2026-05-16T00:00:00Z")], 100)
            self.assertNotIn(_bucket("2026-05-17T02:00:00Z"), hourly_totals)
            self.assertEqual(sum(hourly_totals.values()), 100)


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
            "\n".join(
                [_session_meta_line("/tmp/cache-project")]
                + [_token_count_line(f"2026-05-16T0{index}:00:00Z", total) for index, total in enumerate(totals)]
            )
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

    def test_get_token_project_usage_by_date_range(self):
        self._write_jsonl([100, 250])

        usage = storage.get_token_project_usage_by_date_range("2026-05-16", "2026-05-16", roots=[self.root])

        self.assertEqual(
            usage["2026-05-16"],
            [
                {
                    "project": "cache-project",
                    "tokens": 250,
                }
            ],
        )

    def test_icloud_backup_failure_does_not_raise(self):
        storage.get_connection()
        icloud_root = Path(self.tmp.name) / "icloud"
        icloud_backup_dir = icloud_root / "WorkIntensity"
        icloud_backup_dir.mkdir(parents=True)
        storage._ICLOUD_ROOT_DIR = str(icloud_root)
        storage._ICLOUD_BACKUP_DIR = str(icloud_backup_dir)
        storage._ICLOUD_DB_PATH = str(icloud_backup_dir / "work_intensity.sqlite3")

        original_connect = storage.sqlite3.connect

        def failing_connect(path, *args, **kwargs):
            if path == storage._ICLOUD_DB_PATH + ".tmp":
                raise sqlite3.OperationalError("unable to open database file")
            return original_connect(path, *args, **kwargs)

        try:
            storage.sqlite3.connect = failing_connect
            self.assertFalse(storage.sync_to_icloud(force=True))
        finally:
            storage.sqlite3.connect = original_connect

    def test_get_icloud_backup_time_uses_backup_file_mtime(self):
        backup_file = self.log_dir / "backup.sqlite3"
        backup_file.parent.mkdir()
        backup_file.write_text("", encoding="utf-8")
        expected_timestamp = datetime(2026, 6, 1, 14, 5).timestamp()
        os.utime(backup_file, (expected_timestamp, expected_timestamp))
        storage._ICLOUD_DB_PATH = str(backup_file)

        self.assertEqual(storage.get_icloud_backup_time(), datetime.fromtimestamp(expected_timestamp))


if __name__ == "__main__":
    unittest.main()
