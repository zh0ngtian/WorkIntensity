import os
import re
import sqlite3
import threading
import time
from datetime import date, datetime

import token_usage


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
_TOKEN_USAGE_FINGERPRINT_KEY = "token_usage_fingerprint"
_TOKEN_USAGE_TOTALS_CHECKSUM_KEY = "token_usage_totals_checksum"
_TOKEN_SCALE_STRENGTH_SETTING_KEY = "token_scale_strength"


def _ensure_log_dir():
    os.makedirs(_LOG_DIR, exist_ok=True)


def _icloud_available():
    return os.path.isdir(_ICLOUD_ROOT_DIR)


def _ensure_icloud_backup_dir():
    if not _icloud_available():
        return False
    os.makedirs(_ICLOUD_BACKUP_DIR, exist_ok=True)
    return True


def get_icloud_backup_time():
    try:
        if not os.path.exists(_ICLOUD_DB_PATH):
            return None
        return datetime.fromtimestamp(os.path.getmtime(_ICLOUD_DB_PATH))
    except OSError:
        return None


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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS token_usage_hourly (
            day TEXT NOT NULL,
            hour INTEGER NOT NULL,
            total_tokens INTEGER NOT NULL,
            PRIMARY KEY (day, hour)
        ) WITHOUT ROWID
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS token_usage_project_daily (
            day TEXT NOT NULL,
            project TEXT NOT NULL,
            total_tokens INTEGER NOT NULL,
            PRIMARY KEY (day, project)
        ) WITHOUT ROWID
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS token_usage_cache_meta (
            key TEXT NOT NULL PRIMARY KEY,
            value TEXT NOT NULL
        ) WITHOUT ROWID
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS token_usage_file_state (
            path TEXT NOT NULL PRIMARY KEY,
            device INTEGER NOT NULL,
            inode INTEGER NOT NULL,
            processed_size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            previous_total INTEGER,
            fallback_model TEXT NOT NULL,
            project TEXT NOT NULL
        ) WITHOUT ROWID
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS token_usage_dedup_event (
            dedup_key TEXT NOT NULL PRIMARY KEY,
            timestamp_us INTEGER NOT NULL,
            day TEXT NOT NULL,
            hour INTEGER NOT NULL,
            delta INTEGER NOT NULL,
            project TEXT NOT NULL
        ) WITHOUT ROWID
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT NOT NULL PRIMARY KEY,
            value TEXT NOT NULL
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


def get_token_scale_strength(default=0):
    conn = get_connection()
    with _DB_LOCK:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            (_TOKEN_SCALE_STRENGTH_SETTING_KEY,),
        ).fetchone()
    if row is None:
        return default
    try:
        return max(0, min(100, int(row[0])))
    except (TypeError, ValueError):
        return default


def set_token_scale_strength(value):
    strength = max(0, min(100, int(value)))
    conn = get_connection()
    with _DB_LOCK:
        conn.execute(
            """
            INSERT INTO app_settings(key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (_TOKEN_SCALE_STRENGTH_SETTING_KEY, str(strength)),
        )
    sync_to_icloud()
    return strength


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


def _get_token_usage_fingerprint(conn):
    row = conn.execute(
        "SELECT value FROM token_usage_cache_meta WHERE key = ?",
        (_TOKEN_USAGE_FINGERPRINT_KEY,),
    ).fetchone()
    return row[0] if row is not None else None


def _calculate_token_usage_totals_checksum(conn):
    hourly_count, hourly_total = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(total_tokens), 0) FROM token_usage_hourly"
    ).fetchone()
    project_count, project_total = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(total_tokens), 0) FROM token_usage_project_daily"
    ).fetchone()
    return f"{hourly_count}:{hourly_total}:{project_count}:{project_total}"


def _get_token_usage_totals_checksum(conn):
    row = conn.execute(
        "SELECT value FROM token_usage_cache_meta WHERE key = ?",
        (_TOKEN_USAGE_TOTALS_CHECKSUM_KEY,),
    ).fetchone()
    return row[0] if row is not None else None


def _store_token_usage_totals_checksum(conn):
    conn.execute(
        """
        INSERT INTO token_usage_cache_meta(key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (_TOKEN_USAGE_TOTALS_CHECKSUM_KEY, _calculate_token_usage_totals_checksum(conn)),
    )


def _replace_token_usage_cache(
    conn,
    fingerprint,
    hourly_totals,
    project_daily_totals,
    deduped_events,
    file_states,
):
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM token_usage_hourly")
        conn.execute("DELETE FROM token_usage_project_daily")
        conn.execute("DELETE FROM token_usage_dedup_event")
        conn.execute("DELETE FROM token_usage_file_state")
        if hourly_totals:
            conn.executemany(
                """
                INSERT INTO token_usage_hourly(day, hour, total_tokens)
                VALUES (?, ?, ?)
                """,
                [
                    (day, hour, total_tokens)
                    for (day, hour), total_tokens in sorted(hourly_totals.items())
                ],
            )
        if project_daily_totals:
            conn.executemany(
                """
                INSERT INTO token_usage_project_daily(day, project, total_tokens)
                VALUES (?, ?, ?)
                """,
                [
                    (day, project, total_tokens)
                    for (day, project), total_tokens in sorted(project_daily_totals.items())
                ],
            )
        if deduped_events:
            conn.executemany(
                """
                INSERT INTO token_usage_dedup_event(
                    dedup_key, timestamp_us, day, hour, delta, project
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (dedup_key, timestamp_us, day, hour, delta, project)
                    for dedup_key, (timestamp_us, day, hour, delta, project) in deduped_events.items()
                ],
            )
        if file_states:
            conn.executemany(
                """
                INSERT INTO token_usage_file_state(
                    path, device, inode, processed_size, mtime_ns,
                    previous_total, fallback_model, project
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        path,
                        state["device"],
                        state["inode"],
                        state["processed_size"],
                        state["mtime_ns"],
                        state["previous_total"],
                        state["fallback_model"],
                        state["project"],
                    )
                    for path, state in file_states.items()
                ],
            )
        conn.execute(
            """
            INSERT INTO token_usage_cache_meta(key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (_TOKEN_USAGE_FINGERPRINT_KEY, fingerprint),
        )
        _store_token_usage_totals_checksum(conn)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _load_token_usage_file_states(conn):
    rows = conn.execute(
        """
        SELECT path, device, inode, processed_size, mtime_ns,
               previous_total, fallback_model, project
        FROM token_usage_file_state
        """
    ).fetchall()
    return {
        row[0]: {
            "device": row[1],
            "inode": row[2],
            "processed_size": row[3],
            "mtime_ns": row[4],
            "previous_total": row[5],
            "fallback_model": row[6],
            "project": row[7],
        }
        for row in rows
    }


def _adjust_hourly_token_total(conn, day, hour, delta):
    conn.execute(
        """
        INSERT INTO token_usage_hourly(day, hour, total_tokens)
        VALUES (?, ?, ?)
        ON CONFLICT(day, hour) DO UPDATE SET
            total_tokens = token_usage_hourly.total_tokens + excluded.total_tokens
        """,
        (day, hour, delta),
    )
    conn.execute(
        "DELETE FROM token_usage_hourly WHERE day = ? AND hour = ? AND total_tokens <= 0",
        (day, hour),
    )


def _adjust_project_token_total(conn, day, project, delta):
    conn.execute(
        """
        INSERT INTO token_usage_project_daily(day, project, total_tokens)
        VALUES (?, ?, ?)
        ON CONFLICT(day, project) DO UPDATE SET
            total_tokens = token_usage_project_daily.total_tokens + excluded.total_tokens
        """,
        (day, project, delta),
    )
    conn.execute(
        "DELETE FROM token_usage_project_daily WHERE day = ? AND project = ? AND total_tokens <= 0",
        (day, project),
    )


def _apply_incremental_token_event(conn, event):
    timestamp_us, day, hour, delta, dedup_key, project = event
    if dedup_key is None:
        _adjust_hourly_token_total(conn, day, hour, delta)
        _adjust_project_token_total(conn, day, project, delta)
        return

    previous = conn.execute(
        """
        SELECT timestamp_us, day, hour, delta, project
        FROM token_usage_dedup_event
        WHERE dedup_key = ?
        """,
        (dedup_key,),
    ).fetchone()
    if previous is not None and not (
        timestamp_us < previous[0] or (timestamp_us == previous[0] and delta > previous[3])
    ):
        return

    if previous is not None:
        _adjust_hourly_token_total(conn, previous[1], previous[2], -previous[3])
        _adjust_project_token_total(conn, previous[1], previous[4], -previous[3])

    _adjust_hourly_token_total(conn, day, hour, delta)
    _adjust_project_token_total(conn, day, project, delta)
    conn.execute(
        """
        INSERT INTO token_usage_dedup_event(
            dedup_key, timestamp_us, day, hour, delta, project
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(dedup_key) DO UPDATE SET
            timestamp_us = excluded.timestamp_us,
            day = excluded.day,
            hour = excluded.hour,
            delta = excluded.delta,
            project = excluded.project
        """,
        (dedup_key, timestamp_us, day, hour, delta, project),
    )


def _full_refresh_token_usage_cache(conn, roots):
    aggregated = token_usage.aggregate_hourly_token_usage(roots)
    with _DB_LOCK:
        _ensure_tables(conn)
        _replace_token_usage_cache(
            conn,
            aggregated["fingerprint"],
            aggregated["hourly_totals"],
            aggregated["project_daily_totals"],
            aggregated["deduped_events"],
            aggregated["file_states"],
        )


def refresh_token_usage_cache_if_needed(roots=None, force=False):
    conn = get_connection()
    file_records = token_usage.iter_jsonl_file_records(roots)
    fingerprint = token_usage.build_fingerprint(file_records)

    with _DB_LOCK:
        cached_fingerprint = _get_token_usage_fingerprint(conn)
        if not force and cached_fingerprint == fingerprint:
            return False
        file_states = _load_token_usage_file_states(conn)
        cached_totals_checksum = _get_token_usage_totals_checksum(conn)
        totals_checksum_matches = cached_totals_checksum == _calculate_token_usage_totals_checksum(conn)

    if force or not file_states or not totals_checksum_matches:
        _full_refresh_token_usage_cache(conn, roots)
        sync_to_icloud()
        return True

    current_files = []
    for path, size, mtime_ns in file_records:
        try:
            stat = os.stat(path)
        except OSError:
            continue
        current_files.append(
            {
                "path": path,
                "size": size,
                "mtime_ns": mtime_ns,
                "device": stat.st_dev,
                "inode": stat.st_ino,
            }
        )

    states_by_identity = {
        (state["device"], state["inode"]): (path, state)
        for path, state in file_states.items()
    }
    states_by_basename = {}
    for path, state in file_states.items():
        states_by_basename.setdefault(os.path.basename(path), []).append((path, state))
    current_paths = {current["path"] for current in current_files}
    matched_state_paths = set()
    updates = []
    unsafe_change = False

    for current in current_files:
        old_path = current["path"]
        state = file_states.get(current["path"])
        if state is None:
            identity_match = states_by_identity.get((current["device"], current["inode"]))
            if identity_match is not None:
                old_path, state = identity_match
        if state is None:
            basename_matches = states_by_basename.get(os.path.basename(current["path"]), [])
            if len(basename_matches) == 1 and basename_matches[0][0] not in current_paths:
                old_path, state = basename_matches[0]

        if state is None:
            scan = token_usage.scan_token_file(current["path"])
        elif current["size"] == state["processed_size"] and (
            current["mtime_ns"] == state["mtime_ns"] or old_path != current["path"]
        ):
            matched_state_paths.add(old_path)
            if old_path != current["path"]:
                updates.append((old_path, current, None, state))
            continue
        elif current["size"] > state["processed_size"]:
            scan = token_usage.scan_token_file(
                current["path"],
                start_offset=state["processed_size"],
                previous_total=state["previous_total"],
                fallback_model=state["fallback_model"],
                project=state["project"],
            )
        else:
            unsafe_change = True
            break

        if not scan["ok"]:
            return False
        try:
            stat = os.stat(current["path"])
        except OSError:
            return False
        current.update(
            {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "device": stat.st_dev,
                "inode": stat.st_ino,
            }
        )
        matched_state_paths.add(old_path)
        updates.append((old_path, current, scan, state))

    if not unsafe_change and set(file_states) - matched_state_paths:
        unsafe_change = True

    if unsafe_change:
        _full_refresh_token_usage_cache(conn, roots)
        sync_to_icloud()
        return True

    try:
        with _DB_LOCK:
            conn.execute("BEGIN")
            for old_path, current, scan, previous_state in updates:
                if scan is None:
                    next_state = previous_state
                else:
                    for event in scan["events"]:
                        _apply_incremental_token_event(conn, event)
                    next_state = {
                        "previous_total": scan["previous_total"],
                        "fallback_model": scan["fallback_model"],
                        "project": scan["project"],
                        "processed_size": scan["processed_size"],
                    }

                if old_path != current["path"]:
                    conn.execute("DELETE FROM token_usage_file_state WHERE path = ?", (old_path,))
                conn.execute(
                    """
                    INSERT INTO token_usage_file_state(
                        path, device, inode, processed_size, mtime_ns,
                        previous_total, fallback_model, project
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        device = excluded.device,
                        inode = excluded.inode,
                        processed_size = excluded.processed_size,
                        mtime_ns = excluded.mtime_ns,
                        previous_total = excluded.previous_total,
                        fallback_model = excluded.fallback_model,
                        project = excluded.project
                    """,
                    (
                        current["path"],
                        current["device"],
                        current["inode"],
                        next_state["processed_size"],
                        current["mtime_ns"],
                        next_state["previous_total"],
                        next_state["fallback_model"],
                        next_state["project"],
                    ),
                )
            conn.execute(
                """
                INSERT INTO token_usage_cache_meta(key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (_TOKEN_USAGE_FINGERPRINT_KEY, fingerprint),
            )
            _store_token_usage_totals_checksum(conn)
            conn.execute("COMMIT")
    except Exception:
        with _DB_LOCK:
            conn.execute("ROLLBACK")
        raise

    if updates:
        sync_to_icloud()
    return bool(updates)


def get_token_usage_by_date_range(start_value, end_value, roots=None, refresh=True):
    start_day = _date_to_day_key(start_value)
    end_day = _date_to_day_key(end_value)
    if refresh:
        refresh_token_usage_cache_if_needed(roots=roots)

    conn = get_connection()
    with _DB_LOCK:
        rows = conn.execute(
            """
            SELECT day, hour, total_tokens
            FROM token_usage_hourly
            WHERE day >= ? AND day <= ?
            ORDER BY day ASC, hour ASC
            """,
            (start_day, end_day),
        ).fetchall()

    usage_by_day = {}
    current_day = _normalize_date(start_value)
    final_day = _normalize_date(end_value)
    while current_day <= final_day:
        usage_by_day[_date_to_day_key(current_day)] = [0 for _ in range(24)]
        current_day = date.fromordinal(current_day.toordinal() + 1)

    for day, hour, total_tokens in rows:
        if day in usage_by_day and 0 <= hour < 24:
            usage_by_day[day][hour] = int(total_tokens or 0)
    return usage_by_day


def get_token_project_usage_by_date_range(start_value, end_value, roots=None, refresh=True):
    start_day = _date_to_day_key(start_value)
    end_day = _date_to_day_key(end_value)
    if refresh:
        refresh_token_usage_cache_if_needed(roots=roots)

    conn = get_connection()
    with _DB_LOCK:
        rows = conn.execute(
            """
            SELECT day, project, total_tokens
            FROM token_usage_project_daily
            WHERE day >= ? AND day <= ?
            ORDER BY day ASC, total_tokens DESC, project ASC
            """,
            (start_day, end_day),
        ).fetchall()

    usage_by_day = {}
    current_day = _normalize_date(start_value)
    final_day = _normalize_date(end_value)
    while current_day <= final_day:
        usage_by_day[_date_to_day_key(current_day)] = []
        current_day = date.fromordinal(current_day.toordinal() + 1)

    for day, project, total_tokens in rows:
        if day in usage_by_day:
            usage_by_day[day].append(
                {
                    "project": project,
                    "tokens": int(total_tokens or 0),
                }
            )
    return usage_by_day


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
    if not os.access(_ICLOUD_BACKUP_DIR, os.W_OK):
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
    except (OSError, sqlite3.Error):
        return False
    finally:
        if backup_conn is not None:
            backup_conn.close()
        if os.path.exists(backup_temp_path):
            try:
                os.remove(backup_temp_path)
            except OSError:
                pass
