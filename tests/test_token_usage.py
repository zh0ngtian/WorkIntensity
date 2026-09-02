import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

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
    local_time = datetime.fromisoformat(timestamp[:-1] + "+00:00").astimezone() - timedelta(hours=5)
    return local_time.strftime("%Y-%m-%d"), local_time.hour


class TokenUsageAggregationTest(unittest.TestCase):
    def test_utc_events_use_local_five_am_boundary_and_keep_real_timestamps(self):
        local_times = [
            datetime(2026, 5, 31, 5),
            datetime(2026, 6, 1, 0),
            datetime(2026, 6, 1, 4, 59, 59),
            datetime(2026, 6, 1, 5),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            lines = [_session_meta_line("/tmp/boundary-project")]
            for index, local_time in enumerate(local_times, start=1):
                utc_time = local_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                lines.append(_detailed_token_count_line(utc_time, index * 100, index * 100, 100))
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            result = token_usage.aggregate_hourly_token_usage([Path(tmp)])

        self.assertEqual(result["hourly_totals"], {
            ("2026-05-31", 0): 100, ("2026-05-31", 19): 100,
            ("2026-05-31", 23): 100, ("2026-06-01", 0): 100,
        })
        self.assertEqual(result["project_daily_totals"], {
            ("2026-05-31", "boundary-project"): 300,
            ("2026-06-01", "boundary-project"): 100,
        })
        self.assertEqual(
            sorted(event[0] for event in result["deduped_events"].values()),
            [int(local_time.timestamp() * 1_000_000) for local_time in local_times],
        )

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

    def test_old_cache_is_rebuilt_once_even_when_files_are_unchanged(self):
        path = self.root / "session.jsonl"
        path.write_text(
            _session_meta_line("/tmp/boundary-project") + "\n"
            + _detailed_token_count_line("2026-01-01T04:59:59", 100, 100, 100) + "\n"
            + _detailed_token_count_line("2026-01-01T05:00:00", 250, 250, 150) + "\n",
            encoding="utf-8",
        )
        conn = storage.get_connection()
        # Build the old midnight cache, including valid incremental file states.
        with patch.object(token_usage, "reporting_date", lambda value: value.date()), patch.object(
            token_usage, "reporting_hour", lambda value: value.hour
        ):
            storage.refresh_token_usage_cache_if_needed(roots=[self.root])
        original_states = storage._load_token_usage_file_states(conn)

        for old_version in (None, "token_usage_v4_incremental"):
            with self.subTest(old_version=old_version):
                conn.execute("DELETE FROM token_usage_cache_meta WHERE key = ?", (storage._TOKEN_USAGE_VERSION_KEY,))
                if old_version is not None:
                    conn.execute("INSERT INTO token_usage_cache_meta VALUES (?, ?)", (storage._TOKEN_USAGE_VERSION_KEY, old_version))
                with patch.object(token_usage, "aggregate_hourly_token_usage", wraps=token_usage.aggregate_hourly_token_usage) as aggregate:
                    usage = storage.get_token_usage_by_date_range("2025-12-31", "2026-01-01", roots=[self.root])
                    self.assertFalse(storage.refresh_token_usage_cache_if_needed(roots=[self.root]))
                    aggregate.assert_called_once_with([self.root])
                self.assertEqual(usage["2025-12-31"], [0] * 23 + [100])
                self.assertEqual(usage["2026-01-01"], [150] + [0] * 23)
                projects = storage.get_token_project_usage_by_date_range("2025-12-31", "2026-01-01", refresh=False)
                self.assertEqual(projects, {
                    "2025-12-31": [{"project": "boundary-project", "tokens": 100}],
                    "2026-01-01": [{"project": "boundary-project", "tokens": 150}],
                })
                self.assertEqual(storage._load_token_usage_file_states(conn), original_states)
                self.assertEqual(conn.execute(
                    "SELECT day, hour, delta FROM token_usage_dedup_event ORDER BY timestamp_us"
                ).fetchall(), [("2025-12-31", 23, 100), ("2026-01-01", 0, 150)])

    def test_incremental_events_cross_five_am_without_rebuilding_or_double_counting(self):
        path = self.root / "session.jsonl"
        path.write_text(
            _session_meta_line("/tmp/boundary-project") + "\n"
            + _detailed_token_count_line("2026-01-01T04:59:59", 100, 100, 100) + "\n",
            encoding="utf-8",
        )
        before = datetime(2026, 1, 1, 4, 59, 59)
        initial = storage.get_token_usage_by_date_range(before, before, roots=[self.root])
        self.assertEqual(initial, {"2025-12-31": [0] * 23 + [100]})
        with path.open("a", encoding="utf-8") as file:
            file.write(_detailed_token_count_line("2026-01-01T05:00:00", 250, 250, 150) + "\n")
            file.write(_detailed_token_count_line("2026-01-01T05:01:00", 250, 250, 150) + "\n")
        with patch.object(token_usage, "aggregate_hourly_token_usage", side_effect=AssertionError("unexpected full rebuild")):
            usage = storage.get_token_usage_by_date_range("2025-12-31", "2026-01-01", roots=[self.root])
        self.assertEqual(usage["2025-12-31"], [0] * 23 + [100])
        self.assertEqual(usage["2026-01-01"], [150] + [0] * 23)
        self.assertEqual(storage.get_token_project_usage_by_date_range(before, before, refresh=False), {
            "2025-12-31": [{"project": "boundary-project", "tokens": 100}],
        })

    def test_token_scale_strength_is_persisted_and_clamped(self):
        self.assertEqual(storage.get_token_scale_strength(), 0)
        self.assertEqual(storage.set_token_scale_strength(73), 73)
        self.assertEqual(storage.get_token_scale_strength(), 73)
        self.assertEqual(storage.set_token_scale_strength(999), 100)
        self.assertEqual(storage.get_token_scale_strength(), 100)
        self.assertIsNone(storage._DB_CONN)

    def test_token_display_range_is_persisted_and_clamped(self):
        self.assertEqual(storage.get_token_display_range(), (0, 100))
        self.assertEqual(storage.set_token_display_range(20, 85), (20, 85))
        self.assertEqual(storage.get_token_display_range(), (20, 85))
        self.assertEqual(storage.set_token_display_range(-5, 999), (0, 100))
        self.assertEqual(storage.set_token_display_range(100, 20), (99, 100))
        self.assertIsNone(storage._DB_CONN)

    def test_slider_settings_do_not_trigger_icloud_sync(self):
        original_sync = storage.sync_to_icloud
        storage.sync_to_icloud = lambda *_args, **_kwargs: self.fail("unexpected iCloud sync")
        try:
            storage.set_token_scale_strength(50)
            storage.set_token_display_range(10, 90)
        finally:
            storage.sync_to_icloud = original_sync

    def test_cache_reads_only_appended_jsonl_content(self):
        path = self._write_jsonl([100])
        storage.get_token_usage_by_date_range("2026-05-16", "2026-05-16", roots=[self.root])

        original_aggregate = token_usage.aggregate_hourly_token_usage
        token_usage.aggregate_hourly_token_usage = lambda _roots=None: self.fail("unexpected full rebuild")
        try:
            with path.open("a", encoding="utf-8") as file:
                file.write(_token_count_line("2026-05-16T01:00:00Z", 250) + "\n")
            usage = storage.get_token_usage_by_date_range("2026-05-16", "2026-05-16", roots=[self.root])
        finally:
            token_usage.aggregate_hourly_token_usage = original_aggregate

        self.assertEqual(sum(usage["2026-05-16"]), 250)

    def test_incremental_new_fork_preserves_global_deduplication(self):
        original = self.root / "original.jsonl"
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
        storage.get_token_usage_by_date_range("2026-05-16", "2026-05-17", roots=[self.root])

        fork = self.root / "fork.jsonl"
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

        usage = storage.get_token_usage_by_date_range("2026-05-16", "2026-05-17", roots=[self.root])

        self.assertEqual(sum(sum(hours) for hours in usage.values()), 400)
        self.assertEqual(usage[_bucket("2026-05-17T02:00:00Z")[0]][_bucket("2026-05-17T02:00:00Z")[1]], 0)
        self.assertEqual(usage[_bucket("2026-05-17T03:00:00Z")[0]][_bucket("2026-05-17T03:00:00Z")[1]], 150)

    def test_truncated_jsonl_falls_back_to_full_rebuild(self):
        self._write_jsonl([100, 250])
        storage.get_token_usage_by_date_range("2026-05-16", "2026-05-16", roots=[self.root])

        original_aggregate = token_usage.aggregate_hourly_token_usage
        aggregate_calls = []

        def counted_aggregate(roots=None):
            aggregate_calls.append(True)
            return original_aggregate(roots)

        token_usage.aggregate_hourly_token_usage = counted_aggregate
        try:
            self._write_jsonl([50])
            usage = storage.get_token_usage_by_date_range("2026-05-16", "2026-05-16", roots=[self.root])
        finally:
            token_usage.aggregate_hourly_token_usage = original_aggregate

        self.assertEqual(sum(usage["2026-05-16"]), 50)
        self.assertEqual(len(aggregate_calls), 1)

    def test_incremental_reader_waits_for_complete_jsonl_line(self):
        path = self._write_jsonl([100])
        storage.get_token_usage_by_date_range("2026-05-16", "2026-05-16", roots=[self.root])
        next_line = _token_count_line("2026-05-16T01:00:00Z", 250)
        split_index = len(next_line) // 2

        with path.open("a", encoding="utf-8") as file:
            file.write(next_line[:split_index])
        partial = storage.get_token_usage_by_date_range("2026-05-16", "2026-05-16", roots=[self.root])

        with path.open("a", encoding="utf-8") as file:
            file.write(next_line[split_index:] + "\n")
        complete = storage.get_token_usage_by_date_range("2026-05-16", "2026-05-16", roots=[self.root])

        self.assertEqual(sum(partial["2026-05-16"]), 100)
        self.assertEqual(sum(complete["2026-05-16"]), 250)

    def test_incremental_earlier_dedup_event_replaces_cached_replay(self):
        replay = self.root / "replay.jsonl"
        replay.write_text(
            _detailed_token_count_line("2026-05-17T02:00:00Z", 100, 100, 100) + "\n",
            encoding="utf-8",
        )
        storage.get_token_usage_by_date_range("2026-05-16", "2026-05-17", roots=[self.root])

        original = self.root / "original.jsonl"
        original.write_text(
            _detailed_token_count_line("2026-05-16T02:00:00Z", 100, 100, 100) + "\n",
            encoding="utf-8",
        )
        usage = storage.get_token_usage_by_date_range("2026-05-16", "2026-05-17", roots=[self.root])

        original_day, original_hour = _bucket("2026-05-16T02:00:00Z")
        replay_day, replay_hour = _bucket("2026-05-17T02:00:00Z")
        self.assertEqual(usage[original_day][original_hour], 100)
        self.assertEqual(usage[replay_day][replay_hour], 0)

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
