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
_ICLOUD_ROOT_DIR = os.path.join(os.path.expanduser("~"), "Library", "Mobile Documents", "com~apple~CloudDocs")
_ICLOUD_BACKUP_DIR = os.path.join(_ICLOUD_ROOT_DIR, "WorkIntensity")
_ICLOUD_DB_PATH = os.path.join(_ICLOUD_BACKUP_DIR, "work_intensity.sqlite3")
_LEGACY_TIMESTAMP_PATTERN = re.compile(r"\[(\d{2}:\d{2}:\d{2})\]")
_LEGACY_LOG_FILE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}\.log$")
_BLOCK_DURATION_SECONDS = 36
_BLOCKS_PER_DAY = 24 * 100
_ICLOUD_BACKUP_INTERVAL_SECONDS = 300
_LAST_ICLOUD_BACKUP_AT = 0.0


def _ensure_log_dir():
    os.makedirs(_LOG_DIR, exist_ok=True)


def _icloud_available():
    return os.path.isdir(_ICLOUD_ROOT_DIR)


def _ensure_icloud_backup_dir():
    if not _icloud_available():
        return False
    os.makedirs(_ICLOUD_BACKUP_DIR, exist_ok=True)
    return True


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


def _second_to_block_index(second_of_day):
    return second_of_day // _BLOCK_DURATION_SECONDS


def _block_index_to_second(block_index):
    return block_index * _BLOCK_DURATION_SECONDS


def _ensure_tables(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_blocks (
            day TEXT NOT NULL,
            block_index INTEGER NOT NULL,
            PRIMARY KEY (day, block_index)
        ) WITHOUT ROWID
        """
    )


def _migrate_from_activity_events_if_needed(conn):
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'activity_events'"
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    if row is None:
        return False

    try:
        has_old_data = conn.execute("SELECT 1 FROM activity_events LIMIT 1").fetchone() is not None
    except sqlite3.OperationalError:
        return False

    if has_old_data:
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO activity_blocks(day, block_index)
                SELECT day, CAST(second_of_day / ? AS INTEGER)
                FROM activity_events
                """,
                (_BLOCK_DURATION_SECONDS,),
            )
        except sqlite3.OperationalError:
            return False

    conn.execute("DROP TABLE IF EXISTS activity_events")
    conn.execute("PRAGMA wal_checkpoint(FULL)")
    conn.execute("VACUUM")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return True


def _connect():
    conn = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    _ensure_tables(conn)
    _migrate_from_activity_events_if_needed(conn)
    return conn


def get_connection():
    global _DB_CONN
    with _DB_LOCK:
        if _DB_CONN is None:
            _ensure_log_dir()
            _restore_from_icloud_if_needed()
            _DB_CONN = _connect()
        return _DB_CONN


def record_activity(at_time=None):
    now = at_time or datetime.now()
    day = now.strftime("%Y-%m-%d")
    second_of_day = now.hour * 3600 + now.minute * 60 + now.second
    block_index = _second_to_block_index(second_of_day)
    conn = get_connection()
    try:
        with _DB_LOCK:
            conn.execute(
                "INSERT OR IGNORE INTO activity_blocks(day, block_index) VALUES (?, ?)",
                (day, block_index),
            )
    except sqlite3.OperationalError:
        with _DB_LOCK:
            _ensure_tables(conn)
            conn.execute(
                "INSERT OR IGNORE INTO activity_blocks(day, block_index) VALUES (?, ?)",
                (day, block_index),
            )
    sync_to_icloud()


def _import_legacy_log_if_needed(value):
    day = _date_to_day_key(value)
    conn = get_connection()
    with _DB_LOCK:
        row = conn.execute("SELECT 1 FROM activity_blocks WHERE day = ? LIMIT 1", (day,)).fetchone()
        if row is not None:
            return

    legacy_log_path = _legacy_log_path(day)
    if not os.path.exists(legacy_log_path):
        return

    block_indices = set()
    with open(legacy_log_path, "r", encoding="utf-8") as file:
        for line in file:
            match = _LEGACY_TIMESTAMP_PATTERN.search(line)
            if not match:
                continue
            timestamp = datetime.strptime(match.group(1), "%H:%M:%S")
            second_of_day = timestamp.hour * 3600 + timestamp.minute * 60 + timestamp.second
            block_indices.add(_second_to_block_index(second_of_day))

    if not block_indices:
        return

    rows = [(day, block_index) for block_index in sorted(block_indices)]
    with _DB_LOCK:
        conn.executemany(
            "INSERT OR IGNORE INTO activity_blocks(day, block_index) VALUES (?, ?)",
            rows,
        )


def get_activity_seconds_for_date(value):
    day = _date_to_day_key(value)
    _import_legacy_log_if_needed(day)
    conn = get_connection()
    with _DB_LOCK:
        rows = conn.execute(
            "SELECT block_index FROM activity_blocks WHERE day = ? ORDER BY block_index ASC",
            (day,),
        ).fetchall()
    return [_block_index_to_second(row[0]) for row in rows]


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


def optimize_database():
    conn = get_connection()
    with _DB_LOCK:
        conn.execute("PRAGMA wal_checkpoint(FULL)")
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    sync_to_icloud(force=True)


def _restore_from_icloud_if_needed():
    if os.path.exists(_DB_PATH):
        return False
    if not os.path.exists(_ICLOUD_DB_PATH):
        return False

    source_conn = None
    target_conn = None
    try:
        source_conn = sqlite3.connect(_ICLOUD_DB_PATH)
        target_conn = sqlite3.connect(_DB_PATH)
        source_conn.backup(target_conn)
        return True
    finally:
        if target_conn is not None:
            target_conn.close()
        if source_conn is not None:
            source_conn.close()


def sync_to_icloud(force=False):
    global _LAST_ICLOUD_BACKUP_AT
    if not _ensure_icloud_backup_dir():
        return False

    now = time.monotonic()
    if not force and now - _LAST_ICLOUD_BACKUP_AT < _ICLOUD_BACKUP_INTERVAL_SECONDS:
        return False

    conn = get_connection()
    backup_path = _ICLOUD_DB_PATH
    backup_temp_path = backup_path + ".tmp"
    backup_conn = None
    try:
        with _DB_LOCK:
            conn.execute("PRAGMA wal_checkpoint(FULL)")
            if os.path.exists(backup_temp_path):
                os.remove(backup_temp_path)
            backup_conn = sqlite3.connect(backup_temp_path)
            conn.backup(backup_conn)
        backup_conn.close()
        backup_conn = None
        os.replace(backup_temp_path, backup_path)
        _LAST_ICLOUD_BACKUP_AT = now
        return True
    finally:
        if backup_conn is not None:
            backup_conn.close()
        if os.path.exists(backup_temp_path):
            try:
                os.remove(backup_temp_path)
            except OSError:
                pass
