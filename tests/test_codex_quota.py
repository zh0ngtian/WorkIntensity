import json
import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import codex_quota


class _FakeStdin:
    def __init__(self):
        self.written = bytearray()

    def write(self, value):
        self.written.extend(value)

    def flush(self):
        pass

    def close(self):
        pass


class _FakeProcess:
    def __init__(self, output):
        read_fd, write_fd = os.pipe()
        os.write(write_fd, output)
        os.close(write_fd)
        self.stdin = _FakeStdin()
        self.stdout = os.fdopen(read_fd, "rb", buffering=0)
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


class CodexQuotaTest(unittest.TestCase):
    def test_finds_chatgpt_bundled_codex_when_path_has_no_codex(self):
        with (
            mock.patch("codex_quota.shutil.which", return_value=None),
            mock.patch.object(codex_quota, "_CHATGPT_CODEX_EXECUTABLE", Path(__file__)),
        ):
            executable = codex_quota._find_codex_executable()

        self.assertEqual(executable, __file__)

    def test_extracts_codex_bucket_before_legacy_bucket(self):
        remaining, resets_at = codex_quota._extract_primary_rate_limit(
            {
                "rateLimits": {
                    "primary": {"usedPercent": 90, "resetsAt": 100},
                },
                "rateLimitsByLimitId": {
                    "codex": {
                        "primary": {"usedPercent": 18, "resetsAt": 200},
                    }
                },
            }
        )

        self.assertEqual((remaining, resets_at), (82, 200))

    def test_formats_remaining_percentage_and_reset_countdown(self):
        now = datetime(2026, 7, 31, 10, 0)
        resets_at = int(now.timestamp()) + (2 * 24 + 20) * 3600

        self.assertEqual(codex_quota.format_quota_status(82, resets_at, now), "82% · 2d20h(40%)")

    def test_reset_countdown_percentage_is_capped_at_one_hundred(self):
        now = datetime(2026, 7, 31, 10, 0)
        resets_at = int(now.timestamp()) + (7 * 24 + 12) * 3600

        self.assertEqual(codex_quota.format_quota_status(82, resets_at, now), "82% · 7d12h(100%)")

    def test_fetch_uses_official_app_server_protocol(self):
        now = datetime(2026, 7, 31, 10, 0)
        resets_at = int(now.timestamp()) + (7 * 24 + 12) * 3600
        response = {
            "id": 1,
            "result": {
                "rateLimits": {
                    "primary": {"usedPercent": 18, "resetsAt": resets_at},
                }
            },
        }
        process = _FakeProcess(
            b'{"method":"account/rateLimits/updated","params":{}}\n'
            + json.dumps(response).encode("utf-8")
            + b"\n"
        )

        with (
            mock.patch("codex_quota._find_codex_executable", return_value="/path/to/codex"),
            mock.patch("codex_quota.subprocess.Popen", return_value=process) as popen,
        ):
            status = codex_quota.fetch_quota_status(now=now)

        self.assertEqual(status, "82% · 7d12h(100%)")
        popen.assert_called_once_with(
            ["/path/to/codex", "app-server"],
            stdin=codex_quota.subprocess.PIPE,
            stdout=codex_quota.subprocess.PIPE,
            stderr=codex_quota.subprocess.DEVNULL,
        )
        requests = [json.loads(line) for line in process.stdin.written.splitlines()]
        self.assertEqual(requests[0]["method"], "initialize")
        self.assertEqual(requests[1]["method"], "initialized")
        self.assertEqual(requests[2]["method"], "account/rateLimits/read")

    def test_fetch_retries_transient_app_server_error(self):
        now = datetime(2026, 7, 31, 10, 0)
        resets_at = int(now.timestamp()) + 3600
        failed_process = _FakeProcess(
            b'{"id":1,"error":{"code":-32603,"message":"temporary failure"}}\n'
        )
        successful_process = _FakeProcess(
            json.dumps(
                {
                    "id": 1,
                    "result": {
                        "rateLimits": {
                            "primary": {"usedPercent": 18, "resetsAt": resets_at},
                        }
                    },
                }
            ).encode("utf-8")
            + b"\n"
        )

        with (
            mock.patch("codex_quota._find_codex_executable", return_value="/path/to/codex"),
            mock.patch(
                "codex_quota.subprocess.Popen",
                side_effect=[failed_process, successful_process],
            ) as popen,
            mock.patch("codex_quota.time.sleep"),
        ):
            status = codex_quota.fetch_quota_status(now=now)

        self.assertEqual(status, "82% · 0d1h(1%)")
        self.assertEqual(popen.call_count, 2)

    def test_fetch_uses_last_known_value_after_transient_errors(self):
        now = datetime(2026, 7, 31, 10, 0)
        resets_at = int(now.timestamp()) + 3600

        with (
            mock.patch.object(codex_quota, "_last_known_rate_limit", (82, resets_at)),
            mock.patch(
                "codex_quota._fetch_quota_status_once",
                side_effect=RuntimeError("temporary failure"),
            ) as fetch,
            mock.patch("codex_quota.time.sleep"),
        ):
            status = codex_quota.fetch_quota_status(now=now)

        self.assertEqual(status, "82% · 0d1h(1%)")
        self.assertEqual(fetch.call_count, 5)


if __name__ == "__main__":
    unittest.main()
