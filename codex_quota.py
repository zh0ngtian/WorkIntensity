import json
import os
import select
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path


_INITIALIZE_REQUEST_ID = 0
_RATE_LIMITS_REQUEST_ID = 1
_CHATGPT_CODEX_EXECUTABLE = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
_QUOTA_WINDOW_HOURS = 7 * 24
_last_known_rate_limit = None


def _find_codex_executable():
    executable = shutil.which("codex")
    if executable:
        return executable
    if _CHATGPT_CODEX_EXECUTABLE.is_file():
        return str(_CHATGPT_CODEX_EXECUTABLE)
    raise FileNotFoundError("Codex executable is unavailable")


def _extract_primary_rate_limit(result):
    buckets = result.get("rateLimitsByLimitId")
    if isinstance(buckets, dict):
        bucket = buckets.get("codex")
    else:
        bucket = None

    if not isinstance(bucket, dict):
        bucket = result.get("rateLimits")
    if not isinstance(bucket, dict):
        raise ValueError("Codex rate limit bucket is unavailable")

    primary = bucket.get("primary")
    if not isinstance(primary, dict):
        raise ValueError("Codex primary rate limit is unavailable")

    used_percent = primary.get("usedPercent")
    resets_at = primary.get("resetsAt")
    if (
        isinstance(used_percent, bool)
        or not isinstance(used_percent, (int, float))
        or isinstance(resets_at, bool)
        or not isinstance(resets_at, (int, float))
    ):
        raise ValueError("Codex rate limit values are invalid")

    remaining_percent = int(round(max(0.0, min(100.0, 100.0 - used_percent))))
    return remaining_percent, int(resets_at)


def format_quota_status(remaining_percent, resets_at, now):
    remaining_seconds = max(0, resets_at - int(now.timestamp()))
    remaining_hours = remaining_seconds // 3600
    days, hours = divmod(remaining_hours, 24)
    remaining_time_percent = int(round(remaining_hours / _QUOTA_WINDOW_HOURS * 100))
    remaining_time_percent = max(0, min(100, remaining_time_percent))
    return f"{remaining_percent}% · {days}d{hours}h({remaining_time_percent}%)"


def _request_payload():
    messages = [
        {
            "method": "initialize",
            "id": _INITIALIZE_REQUEST_ID,
            "params": {
                "clientInfo": {
                    "name": "work_intensity",
                    "title": "WorkIntensity",
                    "version": "0.1.0",
                }
            },
        },
        {"method": "initialized", "params": {}},
        {"method": "account/rateLimits/read", "id": _RATE_LIMITS_REQUEST_ID},
    ]
    return b"".join(
        json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n" for message in messages
    )


def _stop_process(process):
    for stream in (process.stdin, process.stdout):
        try:
            stream.close()
        except (AttributeError, OSError):
            pass

    if process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _fetch_quota_status_once(now, timeout_seconds):
    process = subprocess.Popen(
        [_find_codex_executable(), "app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    try:
        process.stdin.write(_request_payload())
        process.stdin.flush()

        deadline = time.monotonic() + timeout_seconds
        buffer = bytearray()

        while True:
            remaining_timeout = deadline - time.monotonic()
            if remaining_timeout <= 0:
                raise TimeoutError("Timed out waiting for Codex rate limits")

            ready, _, _ = select.select([process.stdout], [], [], remaining_timeout)
            if not ready:
                raise TimeoutError("Timed out waiting for Codex rate limits")

            chunk = os.read(process.stdout.fileno(), 4096)
            if not chunk:
                raise RuntimeError("Codex app-server closed before returning rate limits")
            buffer.extend(chunk)

            while b"\n" in buffer:
                line, _, remainder = buffer.partition(b"\n")
                buffer = bytearray(remainder)
                try:
                    response = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                if response.get("id") != _RATE_LIMITS_REQUEST_ID:
                    continue
                if "error" in response:
                    raise RuntimeError("Codex app-server could not return rate limits")

                return _extract_primary_rate_limit(response.get("result", {}))
    finally:
        _stop_process(process)


def fetch_quota_status(now=None, timeout_seconds=5):
    global _last_known_rate_limit

    current_time = now or datetime.now()
    deadline = time.monotonic() + timeout_seconds
    last_error = None

    for attempt in range(5):
        remaining_timeout = deadline - time.monotonic()
        if remaining_timeout <= 0:
            break
        try:
            _last_known_rate_limit = _fetch_quota_status_once(current_time, remaining_timeout)
            return format_quota_status(*_last_known_rate_limit, current_time)
        except RuntimeError as error:
            last_error = error
            if attempt == 4:
                break
            remaining_timeout = deadline - time.monotonic()
            if remaining_timeout <= 0:
                break
            time.sleep(min(0.25, remaining_timeout))

    if _last_known_rate_limit is not None:
        return format_quota_status(*_last_known_rate_limit, current_time)
    if last_error is not None:
        raise last_error
    raise TimeoutError("Timed out waiting for Codex rate limits")
