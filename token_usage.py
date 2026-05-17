import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


DEFAULT_CODEX_ROOTS = (
    Path.home() / ".codex" / "sessions",
    Path.home() / ".codex" / "archived_sessions",
)


def iter_jsonl_file_records(roots=None):
    records = []
    for root in roots or DEFAULT_CODEX_ROOTS:
        root_path = Path(root).expanduser()
        if not root_path.exists():
            continue
        for path in root_path.rglob("*.jsonl"):
            try:
                stat = path.stat()
            except OSError:
                continue
            records.append((str(path), stat.st_size, stat.st_mtime_ns))
    return sorted(records)


def build_fingerprint(file_records):
    digest = hashlib.sha256()
    for path, size, mtime_ns in file_records:
        digest.update(path.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(mtime_ns).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _parse_local_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value[:-1] + "+00:00").astimezone()
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone() if parsed.tzinfo is not None else parsed


def _extract_total_tokens(obj):
    if obj.get("type") != "event_msg":
        return None

    payload = obj.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None

    info = payload.get("info")
    if not isinstance(info, dict):
        return None

    total_usage = info.get("total_token_usage")
    if not isinstance(total_usage, dict):
        return None

    total_tokens = total_usage.get("total_tokens")
    if isinstance(total_tokens, bool) or not isinstance(total_tokens, int):
        return None
    return total_tokens


def _iter_token_events(path):
    try:
        with Path(path).open("r", encoding="utf-8") as file:
            for line in file:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                total_tokens = _extract_total_tokens(obj)
                if total_tokens is None:
                    continue

                yield obj.get("timestamp"), total_tokens
    except OSError:
        return


def aggregate_hourly_token_usage(roots=None):
    file_records = iter_jsonl_file_records(roots)
    hourly_totals = defaultdict(int)

    for path, _size, _mtime_ns in file_records:
        previous_total = None
        for timestamp, total_tokens in _iter_token_events(path):
            if previous_total is None:
                delta = total_tokens
            elif total_tokens > previous_total:
                delta = total_tokens - previous_total
            elif total_tokens < previous_total:
                delta = total_tokens
            else:
                delta = 0
            previous_total = total_tokens

            if delta <= 0:
                continue

            local_timestamp = _parse_local_timestamp(timestamp)
            if local_timestamp is None:
                continue

            day = local_timestamp.strftime("%Y-%m-%d")
            hourly_totals[(day, local_timestamp.hour)] += delta

    return {
        "fingerprint": build_fingerprint(file_records),
        "hourly_totals": dict(hourly_totals),
    }
