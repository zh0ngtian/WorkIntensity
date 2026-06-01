import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


DEFAULT_CODEX_ROOTS = (
    Path.home() / ".codex" / "sessions",
    Path.home() / ".codex" / "archived_sessions",
)
_FINGERPRINT_VERSION = "token_usage_v2_fork_dedupe"


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


def _extract_token_event(obj, fallback_model=""):
    total_tokens = _extract_total_tokens(obj)
    if total_tokens is None:
        return None

    info = obj["payload"]["info"]
    return obj.get("timestamp"), total_tokens, _codex_token_dedup_key(info, fallback_model)


def _iter_token_events(path):
    try:
        fallback_model = ""
        with Path(path).open("r", encoding="utf-8", errors="replace") as file:
            for line in file:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if obj.get("type") == "turn_context":
                    payload = obj.get("payload")
                    if isinstance(payload, dict):
                        model = payload.get("model")
                        if isinstance(model, str) and model:
                            fallback_model = model

                event = _extract_token_event(obj, fallback_model)
                if event is None:
                    continue

                yield event
    except OSError:
        return


def aggregate_hourly_token_usage(roots=None):
    file_records = iter_jsonl_file_records(roots)
    hourly_totals = defaultdict(int)
    deduped_events = {}

    for path, _size, _mtime_ns in file_records:
        previous_total = None
        for timestamp, total_tokens, dedup_key in _iter_token_events(path):
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

            if dedup_key is None:
                day = local_timestamp.strftime("%Y-%m-%d")
                hourly_totals[(day, local_timestamp.hour)] += delta
                continue

            previous_event = deduped_events.get(dedup_key)
            if (
                previous_event is None
                or local_timestamp < previous_event[0]
                or (local_timestamp == previous_event[0] and delta > previous_event[1])
            ):
                deduped_events[dedup_key] = (local_timestamp, delta)

    for local_timestamp, delta in deduped_events.values():
        day = local_timestamp.strftime("%Y-%m-%d")
        hourly_totals[(day, local_timestamp.hour)] += delta

    return {
        "fingerprint": build_fingerprint(file_records),
        "hourly_totals": dict(hourly_totals),
    }
