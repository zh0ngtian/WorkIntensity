import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


DEFAULT_CODEX_ROOTS = (
    Path.home() / ".codex" / "sessions",
    Path.home() / ".codex" / "archived_sessions",
)
_FINGERPRINT_VERSION = "token_usage_v4_incremental"
_UNKNOWN_PROJECT = "unknown"


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
    digest.update(_FINGERPRINT_VERSION.encode("ascii"))
    digest.update(b"\n")
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


def _project_name_from_cwd(value):
    if not isinstance(value, str) or not value.strip():
        return _UNKNOWN_PROJECT
    name = Path(value).expanduser().name
    return name or _UNKNOWN_PROJECT


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


def _json_int(obj, key):
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _has_component_usage_detail(usage):
    return any(
        key in usage and isinstance(usage.get(key), int) and not isinstance(usage.get(key), bool)
        for key in (
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "cache_read_input_tokens",
            "reasoning_output_tokens",
        )
    )


def _codex_token_dedup_key(info, fallback_model):
    total_usage = info.get("total_token_usage")
    if not isinstance(total_usage, dict):
        return None

    usage = info.get("last_token_usage")
    if not isinstance(usage, dict):
        usage = total_usage if _has_component_usage_detail(total_usage) else None
    if not isinstance(usage, dict) or not (
        _has_component_usage_detail(usage) or _has_component_usage_detail(total_usage)
    ):
        return None

    model = info.get("model")
    if not isinstance(model, str) or not model:
        model = fallback_model or ""

    cached_input = _json_int(usage, "cached_input_tokens") + _json_int(usage, "cache_read_input_tokens")
    reasoning_output = _json_int(usage, "reasoning_output_tokens")
    input_tokens = max(0, _json_int(usage, "input_tokens") - cached_input)
    output_tokens = max(0, _json_int(usage, "output_tokens") - reasoning_output)

    digest = hashlib.sha256()
    digest.update(
        "|".join(
            (
                "codex-token",
                model,
                str(input_tokens),
                str(output_tokens),
                str(cached_input),
                str(reasoning_output),
                str(_json_int(usage, "total_tokens")),
                str(_json_int(total_usage, "input_tokens")),
                str(_json_int(total_usage, "output_tokens")),
                str(_json_int(total_usage, "total_tokens")),
            )
        ).encode("utf-8")
    )
    return "codex:" + digest.hexdigest()[:32]


def _extract_token_event(obj, fallback_model="", project=_UNKNOWN_PROJECT):
    total_tokens = _extract_total_tokens(obj)
    if total_tokens is None:
        return None

    info = obj["payload"]["info"]
    return obj.get("timestamp"), total_tokens, _codex_token_dedup_key(info, fallback_model), project


def _iter_token_events(path):
    try:
        fallback_model = ""
        project = _UNKNOWN_PROJECT
        with Path(path).open("r", encoding="utf-8", errors="replace") as file:
            for line in file:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                payload = obj.get("payload")
                if obj.get("type") == "session_meta" and isinstance(payload, dict):
                    project = _project_name_from_cwd(payload.get("cwd"))

                if obj.get("type") == "turn_context":
                    if isinstance(payload, dict):
                        model = payload.get("model")
                        if isinstance(model, str) and model:
                            fallback_model = model
                        if "cwd" in payload:
                            project = _project_name_from_cwd(payload.get("cwd"))

                event = _extract_token_event(obj, fallback_model, project)
                if event is None:
                    continue

                yield event
    except OSError:
        return


def scan_token_file(path, start_offset=0, previous_total=None, fallback_model="", project=_UNKNOWN_PROJECT):
    events = []
    processed_size = start_offset
    try:
        with Path(path).open("rb") as file:
            file.seek(start_offset)
            while True:
                line_start = file.tell()
                line = file.readline()
                if not line:
                    processed_size = file.tell()
                    break
                if not line.endswith(b"\n"):
                    processed_size = line_start
                    break
                processed_size = file.tell()

                try:
                    obj = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue

                payload = obj.get("payload")
                if obj.get("type") == "session_meta" and isinstance(payload, dict):
                    project = _project_name_from_cwd(payload.get("cwd"))

                if obj.get("type") == "turn_context" and isinstance(payload, dict):
                    model = payload.get("model")
                    if isinstance(model, str) and model:
                        fallback_model = model
                    if "cwd" in payload:
                        project = _project_name_from_cwd(payload.get("cwd"))

                event = _extract_token_event(obj, fallback_model, project)
                if event is None:
                    continue

                timestamp, total_tokens, dedup_key, event_project = event
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
                events.append(
                    (
                        int(local_timestamp.timestamp() * 1_000_000),
                        local_timestamp.strftime("%Y-%m-%d"),
                        local_timestamp.hour,
                        delta,
                        dedup_key,
                        event_project,
                    )
                )
    except OSError:
        return {
            "ok": False,
            "events": [],
            "processed_size": start_offset,
            "previous_total": previous_total,
            "fallback_model": fallback_model,
            "project": project,
        }

    return {
        "ok": True,
        "events": events,
        "processed_size": processed_size,
        "previous_total": previous_total,
        "fallback_model": fallback_model,
        "project": project,
    }


def aggregate_hourly_token_usage(roots=None):
    file_records = iter_jsonl_file_records(roots)
    hourly_totals = defaultdict(int)
    project_daily_totals = defaultdict(int)
    deduped_events = {}
    file_states = {}

    for path, _size, _mtime_ns in file_records:
        scan = scan_token_file(path)
        if not scan["ok"]:
            continue
        try:
            stat = Path(path).stat()
        except OSError:
            continue
        file_states[path] = {
            "device": stat.st_dev,
            "inode": stat.st_ino,
            "processed_size": scan["processed_size"],
            "mtime_ns": stat.st_mtime_ns,
            "previous_total": scan["previous_total"],
            "fallback_model": scan["fallback_model"],
            "project": scan["project"],
        }
        for timestamp_us, day, hour, delta, dedup_key, project in scan["events"]:
            if dedup_key is None:
                hourly_totals[(day, hour)] += delta
                project_daily_totals[(day, project)] += delta
                continue

            previous_event = deduped_events.get(dedup_key)
            if (
                previous_event is None
                or timestamp_us < previous_event[0]
                or (timestamp_us == previous_event[0] and delta > previous_event[3])
            ):
                deduped_events[dedup_key] = (timestamp_us, day, hour, delta, project)

    for _timestamp_us, day, hour, delta, project in deduped_events.values():
        hourly_totals[(day, hour)] += delta
        project_daily_totals[(day, project)] += delta

    return {
        "fingerprint": build_fingerprint(file_records),
        "hourly_totals": dict(hourly_totals),
        "project_daily_totals": dict(project_daily_totals),
        "deduped_events": deduped_events,
        "file_states": file_states,
    }
