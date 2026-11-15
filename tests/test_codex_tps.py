import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from codex_tps import CodexTpsMonitor, TpsTracker, format_tps


class TpsTrackerTest(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.tracker = TpsTracker(clock=lambda: self.now, smoothing_seconds=0)
        self.tracker.reset(connected=True)

    def event(self, method, thread="a", **params):
        self.tracker.handle({"method": method, "params": {"threadId": thread, "turnId": "turn", **params}})

    def usage(self, total, thread="a", reasoning=0, last=0):
        self.event("thread/tokenUsage/updated", thread, tokenUsage={
            "total": {"outputTokens": total, "reasoningOutputTokens": reasoning,
                      "inputTokens": 100000, "cachedInputTokens": 90000},
            "last": {"outputTokens": last, "reasoningOutputTokens": reasoning},
        })

    def test_multiple_threads_sum_independently_and_expire_at_five_seconds(self):
        for tid in ("a", "b"):
            self.tracker.update_thread({"id": tid, "name": tid, "status": {"type": "active"}})
            self.usage(100, tid)
        self.now = 1
        self.usage(120, "a")
        self.usage(110, "b")
        snapshot = self.tracker.snapshot()
        self.assertEqual([row["tps"] for row in snapshot["threads"]], [4, 2])
        self.assertEqual(snapshot["total_tps"], 6)
        self.now = 6
        self.assertEqual(self.tracker.snapshot()["total_tps"], 0)
        self.assertEqual(len(self.tracker.snapshot()["threads"]), 2)

    def test_first_event_is_baseline_not_historical_output(self):
        self.usage(1000000, last=5000)
        self.assertEqual(self.tracker.snapshot()["total_tps"], 0)
        self.usage(1000015, last=15)
        self.assertEqual(self.tracker.snapshot()["total_tps"], 3)

    def test_reasoning_and_tool_calls_count_without_visible_reply(self):
        self.usage(100, reasoning=20)
        self.event("item/started", item={"id": "reasoning", "type": "reasoning"})
        self.event("item/started", item={"id": "tool", "type": "commandExecution"})
        self.usage(150, reasoning=50, last=50)
        # Reasoning is included in outputTokens; adding it again would give 16.
        self.assertEqual(self.tracker.snapshot()["total_tps"], 10)

    def test_streamed_reply_reasoning_and_tool_results_are_not_added_again(self):
        self.usage(100)
        for method in ("item/agentMessage/delta", "item/reasoning/textDelta",
                       "item/reasoning/summaryTextDelta", "item/commandExecution/outputDelta"):
            self.event(method, itemId="item", delta="large streamed content" * 1000)
        self.event("item/completed", item={"id": "old", "type": "agentMessage", "text": "history"})
        self.assertEqual(self.tracker.snapshot()["total_tps"], 0)
        self.usage(125, reasoning=10)
        self.assertEqual(self.tracker.snapshot()["total_tps"], 5)

    def test_duplicates_do_not_count_or_extend_sample_lifetime(self):
        self.usage(100)
        self.now = 2
        self.usage(120, last=20)
        self.now = 6
        self.usage(120, last=20)
        self.assertEqual(self.tracker.snapshot()["total_tps"], 4)
        self.now = 7
        self.assertEqual(self.tracker.snapshot()["total_tps"], 0)

    def test_same_last_count_on_separate_updates_is_not_deduplicated(self):
        self.usage(100)
        self.usage(120, last=20)
        self.usage(140, last=20)
        self.assertEqual(self.tracker.snapshot()["total_tps"], 8)

    def test_delayed_usage_uses_arrival_time_and_does_not_reactivate_completed_thread(self):
        self.usage(100)
        self.event("turn/started")
        self.event("turn/completed")
        self.now = 12
        self.usage(150)
        self.assertEqual(self.tracker.snapshot()["total_tps"], 10)
        self.now = 17
        self.assertEqual(self.tracker.snapshot()["threads"], [])

    def test_lower_counter_establishes_new_baseline_without_negative_output(self):
        self.usage(100)
        self.usage(120)
        self.usage(5)
        self.assertEqual(self.tracker.snapshot()["total_tps"], 4)
        self.usage(15)
        self.assertEqual(self.tracker.snapshot()["total_tps"], 6)

    def test_invalid_usage_does_not_change_baseline(self):
        self.usage(100)
        for total in (None, True, -1, 1.5, "200"):
            self.usage(total)
        for usage in (None, [], {}, {"total": None}, {"total": []}):
            self.event("thread/tokenUsage/updated", tokenUsage=usage)
        self.usage(110)
        self.assertEqual(self.tracker.snapshot()["total_tps"], 2)

    def test_server_requests_do_not_change_usage(self):
        self.usage(100)
        self.tracker.handle({"id": "approval", "method": "thread/tokenUsage/updated", "params": {
            "threadId": "a", "tokenUsage": {"total": {"outputTokens": 200}},
        }})
        self.assertEqual(self.tracker.snapshot()["total_tps"], 0)
        self.usage(110)
        self.assertEqual(self.tracker.snapshot()["total_tps"], 2)

    def test_disconnect_clears_samples_and_reconnect_rebaselines(self):
        self.usage(100)
        self.usage(110)
        self.tracker.reset()
        self.assertEqual(self.tracker.snapshot(), {"connected": False, "total_tps": None, "threads": []})
        self.tracker.reset(connected=True)
        self.usage(200)
        self.assertEqual(self.tracker.snapshot()["total_tps"], 0)
        self.usage(205)
        self.assertEqual(self.tracker.snapshot()["total_tps"], 1)

    def test_unloaded_threads_age_out_and_long_titles_are_normalized(self):
        self.tracker.update_thread({"id": "a", "name": "title\n" + "x" * 60, "status": {"type": "active"}})
        self.usage(100)
        self.usage(105)
        self.tracker.retain_threads(set())
        self.assertLessEqual(len(self.tracker.snapshot()["threads"][0]["title"]), 49)
        self.assertNotIn("\n", self.tracker.snapshot()["threads"][0]["title"])
        self.now = 5
        self.tracker.flush()
        self.tracker.retain_threads(set())
        self.assertEqual(self.tracker.snapshot()["threads"], [])
        self.usage(500)  # reload must not count the missing interval
        self.assertEqual(self.tracker.snapshot()["total_tps"], 0)

    def test_format_distinguishes_disconnection_and_idle(self):
        self.assertEqual(format_tps(None), "-- TPS")
        self.assertEqual(format_tps(0), "0.0 TPS")
        self.assertEqual(format_tps(32.36), "32.4 TPS")


class TpsSmoothingTest(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.tracker = TpsTracker(clock=lambda: self.now)
        self.tracker.reset(connected=True)

    def usage(self, total, thread="a", tracker=None):
        (tracker or self.tracker).handle({"method": "thread/tokenUsage/updated", "params": {
            "threadId": thread, "tokenUsage": {"total": {"outputTokens": total}},
        }})

    def test_batch_rises_gradually_and_decays_after_raw_window_expires(self):
        self.usage(100)
        self.usage(1100)
        self.assertEqual(self.tracker.snapshot()["total_tps"], 0)
        self.now = 1
        early = self.tracker.snapshot()["total_tps"]
        self.assertGreater(early, 0)
        self.now = 5
        peak = self.tracker.snapshot()["total_tps"]
        self.assertGreater(peak, early)
        self.assertLess(peak, 200)  # unsmoothed: 1000 / 5
        self.now = 6
        self.tracker.flush()
        tail = self.tracker.snapshot()["total_tps"]
        self.assertGreater(tail, 0)
        self.assertLess(tail, peak)
        self.now = 10
        self.assertGreater(self.tracker.snapshot()["total_tps"], 0)
        self.assertLess(self.tracker.snapshot()["total_tps"], tail)

    def test_read_frequency_and_delayed_flush_do_not_change_rate(self):
        sparse = TpsTracker(clock=lambda: self.now)
        sparse.reset(connected=True)
        for tracker in (self.tracker, sparse):
            self.usage(100, tracker=tracker)
            self.usage(200, tracker=tracker)
        for tick in range(1, 81):
            self.now = tick / 10
            self.tracker.snapshot()
            self.tracker.flush()
        self.assertAlmostEqual(self.tracker.snapshot()["total_tps"], sparse.snapshot()["total_tps"])
        self.assertGreater(sparse.snapshot()["total_tps"], 0)

    def test_duplicate_event_does_not_restart_smoothing(self):
        self.usage(100)
        self.usage(200)
        self.now = 7
        before = self.tracker.snapshot()["total_tps"]
        self.usage(200)
        self.assertEqual(self.tracker.snapshot()["total_tps"], before)
        self.now = 8
        self.assertLess(self.tracker.snapshot()["total_tps"], before)

    def test_multiple_threads_sum_and_finished_thread_fades_out(self):
        for tid, total in (("a", 200), ("b", 300)):
            self.usage(100, tid)
            self.usage(total, tid)
            self.tracker.handle({"method": "turn/completed", "params": {"threadId": tid}})
        self.now = 6
        snapshot = self.tracker.snapshot()
        self.assertEqual(len(snapshot["threads"]), 2)
        rates = [row["tps"] for row in snapshot["threads"]]
        self.assertAlmostEqual(rates[1], 2 * rates[0])
        self.assertEqual(snapshot["total_tps"], sum(rates))
        self.now = 60
        self.tracker.flush()
        self.assertEqual(self.tracker.snapshot()["total_tps"], 0)
        self.assertEqual(self.tracker.snapshot()["threads"], [])

    def test_regular_batches_settle_at_average_output_rate(self):
        self.usage(0)
        for second in range(51):
            self.now = second
            if second % 5 == 0:
                self.usage((second // 5 + 1) * 100)
            self.tracker.flush()
        self.assertAlmostEqual(self.tracker.snapshot()["total_tps"], 20, delta=0.01)
        self.now = 51
        self.assertAlmostEqual(self.tracker.snapshot()["total_tps"], 20, delta=0.01)

    def test_smoothing_preserves_total_reported_output_over_time(self):
        self.usage(100)
        self.usage(1100)
        integrated = 0
        for tick in range(1, 1201):
            self.now = tick / 10
            self.tracker.flush()
            integrated += self.tracker.snapshot()["total_tps"] * 0.1
        self.assertAlmostEqual(integrated, 1000, delta=1)

    def test_disconnect_immediately_clears_smoothed_tail(self):
        self.usage(100)
        self.usage(200)
        self.now = 3
        self.assertGreater(self.tracker.snapshot()["total_tps"], 0)
        self.tracker.reset()
        self.assertEqual(self.tracker.snapshot(), {"connected": False, "total_tps": None, "threads": []})
        self.tracker.reset(connected=True)
        self.usage(300)
        self.now = 4
        self.assertEqual(self.tracker.snapshot()["total_tps"], 0)


class TpsTransportTest(unittest.TestCase):
    def test_reconnect_does_not_replay_previous_connection_samples(self):
        from websockets.sync.server import unix_serve

        with tempfile.TemporaryDirectory() as directory:
            socket_path = Path(directory) / "events.sock"
            connections = []
            close_first = threading.Event()

            def handler(connection):
                connections.append(connection)
                first = len(connections) == 1
                for line in connection:
                    message = json.loads(line)
                    method = message["method"]
                    if method == "initialized":
                        continue
                    if method == "initialize":
                        result = {}
                    elif method == "thread/loaded/list":
                        result = {"data": ["a"], "nextCursor": None}
                    else:
                        result = {"thread": {"id": "a", "status": {"type": "active"}}}
                    connection.send(json.dumps({"id": message["id"], "result": result}))
                    if method == "thread/resume":
                        for total in ([100, 105] if first else [105]):
                            connection.send(json.dumps({"method": "thread/tokenUsage/updated", "params": {
                                "threadId": "a", "turnId": "turn",
                                "tokenUsage": {"total": {"outputTokens": total}}}}))
                        if first:
                            close_first.wait(timeout=5)
                            connection.close()
                            return

            with unix_serve(handler, str(socket_path)) as server:
                server_thread = threading.Thread(target=server.serve_forever, daemon=True)
                server_thread.start()
                monitor = CodexTpsMonitor(socket_path)
                monitor.start()
                try:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline and not monitor.snapshot()["total_tps"]:
                        time.sleep(0.01)
                    self.assertGreater(monitor.snapshot()["total_tps"], 0)
                    self.assertLess(monitor.snapshot()["total_tps"], 1)
                    close_first.set()
                    while time.monotonic() < deadline:
                        snapshot = monitor.snapshot()
                        if len(connections) >= 2 and snapshot["connected"]:
                            break
                        time.sleep(0.01)
                    self.assertGreaterEqual(len(connections), 2)
                    self.assertTrue(snapshot["connected"])
                    self.assertEqual(snapshot["total_tps"], 0)
                finally:
                    close_first.set()
                    monitor.stop()
                    server.shutdown()
                    server_thread.join(timeout=2)

    def test_unix_handshake_pagination_subscription_and_websocket_fragments(self):
        from websockets.sync.server import unix_serve

        with tempfile.TemporaryDirectory() as directory:
            socket_path = Path(directory) / "events.sock"
            calls = []
            def handler(connection):
                try:
                    for line in connection:
                        message = json.loads(line)
                        calls.append(message)
                        method, params = message["method"], message["params"]
                        if method == "initialized":
                            continue
                        if method == "initialize":
                            result = {}
                        elif method == "thread/loaded/list":
                            result = {"data": ["b"] if params.get("cursor") else ["a"],
                                      "nextCursor": None if params.get("cursor") else "page2"}
                        elif method == "thread/resume":
                            tid = params["threadId"]
                            result = {"thread": {"id": tid, "name": "Thread " + tid, "status": {"type": "active"}}}
                        else:
                            raise AssertionError(method)
                        frame = json.dumps({"id": message["id"], "result": result})
                        connection.send([frame[:len(frame) // 2], frame[len(frame) // 2:]])
                        if method == "thread/resume":
                            for total in (100, 105):
                                connection.send(json.dumps({"method": "thread/tokenUsage/updated", "params": {
                                    "threadId": tid, "turnId": "turn",
                                    "tokenUsage": {"total": {"outputTokens": total}}}}))
                finally:
                    connection.close()

            with unix_serve(handler, str(socket_path)) as server:
                server_thread = threading.Thread(target=server.serve_forever, daemon=True)
                server_thread.start()
                monitor = CodexTpsMonitor(socket_path)
                monitor.start()
                try:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        snapshot = monitor.snapshot()
                        if snapshot["connected"] and snapshot["total_tps"] and len(snapshot["threads"]) == 2:
                            break
                        time.sleep(0.01)
                    self.assertGreater(snapshot["total_tps"], 0, monitor.error)
                    self.assertLess(snapshot["total_tps"], 2)
                    self.assertEqual([row["title"] for row in snapshot["threads"]], ["Thread a", "Thread b"])
                finally:
                    monitor.stop()
                self.assertFalse(monitor._worker.is_alive())
                self.assertIsNone(monitor.snapshot()["total_tps"])
                server.shutdown()
                server_thread.join(timeout=2)
            joins = [m for m in calls if m["method"] == "thread/resume"]
            self.assertEqual([m["params"] for m in joins], [
                {"threadId": "a", "excludeTurns": True}, {"threadId": "b", "excludeTurns": True},
            ])


if __name__ == "__main__":
    unittest.main()
