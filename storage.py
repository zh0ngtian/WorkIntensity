import os
import re
import sqlite3
import threading
import time
from datetime import date, datetime


_DB_LOCK = threading.Lock()
_DB_CONN = None
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log")
_DB_PATH = os.path.join(_LOG_DIR, "work_intensity.sqlite3")
_LEGACY_TIMESTAMP_PATTERN = re.compile(r"\[(\d{2}:\d{2}:\d{2})\]")
_LEGACY_LOG_FILE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}\.log$")


def _ensure_log_dir():
    os.makedirs(_LOG_DIR, exist_ok=True)


def _normalize_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%d").date()
    raise TypeError(f"Unsupported date value: {value!r}")


def _date_to_day_key(value):
    return _normalize_date(value).strftime("%Y-%m-%d")


def _legacy_log_path(value):
    return os.path.join(_LOG_DIR, f"{_date_to_day_key(value)}.log")


def _connect():
    conn = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_events (
            day TEXT NOT NULL,
            second_of_day INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            PRIMARY KEY (day, second_of_day)
        )
        """
    )
    return conn


def get_connection():
    global _DB_CONN
    with _DB_LOCK:
        if _DB_CONN is None:
            _ensure_log_dir()
            _DB_CONN = _connect()
        return _DB_CONN


def record_activity(at_time=None):
    now = at_time or datetime.now()
    day = now.strftime("%Y-%m-%d")
    second_of_day = now.hour * 3600 + now.minute * 60 + now.second
    created_at = int(now.timestamp())
    conn = get_connection()
    with _DB_LOCK:
        conn.execute(
            "INSERT OR IGNORE INTO activity_events(day, second_of_day, created_at) VALUES (?, ?, ?)",
            (day, second_of_day, created_at),
        )


def _import_legacy_log_if_needed(value):
    day = _date_to_day_key(value)
    conn = get_connection()
    with _DB_LOCK:
        row = conn.execute("SELECT 1 FROM activity_events WHERE day = ? LIMIT 1", (day,)).fetchone()
        if row is not None:
            return

    legacy_log_path = _legacy_log_path(day)
    if not os.path.exists(legacy_log_path):
        return

    seconds = set()
    with open(legacy_log_path, "r", encoding="utf-8") as file:
        for line in file:
            match = _LEGACY_TIMESTAMP_PATTERN.search(line)
            if not match:
                continue
            timestamp = datetime.strptime(match.group(1), "%H:%M:%S")
            seconds.add(timestamp.hour * 3600 + timestamp.minute * 60 + timestamp.second)

    if not seconds:
        return

    created_at = int(time.time())
    rows = [(day, second_of_day, created_at) for second_of_day in sorted(seconds)]
    with _DB_LOCK:
        conn.executemany(
            "INSERT OR IGNORE INTO activity_events(day, second_of_day, created_at) VALUES (?, ?, ?)",
            rows,
        )


def get_activity_seconds_for_date(value):
    day = _date_to_day_key(value)
    _import_legacy_log_if_needed(day)
    conn = get_connection()
    with _DB_LOCK:
        rows = conn.execute(
            "SELECT second_of_day FROM activity_events WHERE day = ? ORDER BY second_of_day ASC",
            (day,),
        ).fetchall()
    return [row[0] for row in rows]


def import_all_legacy_logs():
    _ensure_log_dir()
    imported_days = 0
    imported_files = []
    for file_name in sorted(os.listdir(_LOG_DIR)):
        if not _LEGACY_LOG_FILE_PATTERN.match(file_name):
            continue
        day = file_name[:-4]
        before_count = len(get_activity_seconds_for_date(day))
        legacy_path = os.path.join(_LOG_DIR, file_name)
        if before_count == 0 and os.path.exists(legacy_path):
            _import_legacy_log_if_needed(day)
            after_count = len(get_activity_seconds_for_date(day))
            if after_count > 0:
                imported_days += 1
                imported_files.append(file_name)
    return {
        "imported_days": imported_days,
        "imported_files": imported_files,
    }
