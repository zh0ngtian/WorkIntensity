"""Local Codex output usage rates, independent of daily usage storage."""

import json
import logging
import math
import threading
import time
from collections import deque
from pathlib import Path

WINDOW_SECONDS = 5.0
SMOOTHING_SECONDS = 5.0
ZERO_TPS = 0.05  # Smaller values round to zero at the displayed precision.


def format_tps(value):
    return "-- TPS" if value is None else f"{value:.1f} TPS"


class TpsTracker:
    """Smooth reported output increments independently for each conversation."""

    def __init__(self, clock=time.monotonic, smoothing_seconds=SMOOTHING_SECONDS):
        self._clock = clock
        self._smoothing_seconds = smoothing_seconds
        self._lock = threading.RLock()
        self._threads = {}
        self.connected = False

    def reset(self, connected=False):
        with self._lock:
            self._threads.clear()
            self.connected = connected

    def update_thread(self, thread):
        with self._lock:
            state = self._state(thread["id"])
            title = " ".join((thread.get("name") or thread.get("preview") or thread["id"]).split())
            state["title"] = title[:48] + ("…" if len(title) > 48 else "")
            state["active"] = thread.get("status", {}).get("type") == "active"
            state["parent_id"] = thread.get("parentThreadId")
            state["metadata_loaded"] = True

    def _state(self, thread_id):
        return self._threads.setdefault(thread_id, {
            "title": thread_id, "active": False, "samples": deque(),
            "usage_total": None, "parent_id": None, "metadata_loaded": False,
        })

    def handle(self, message):
        # Server approval requests belong to the desktop, never this observer.
        if "id" in message:
            return
        method, params = message.get("method"), message.get("params", {})
        if method == "thread/started":
            self.update_thread(params["thread"])
            return
        thread_id = params.get("threadId")
        if not thread_id:
            return
        with self._lock:
            state = self._state(thread_id)
            if method == "thread/status/changed":
                state["active"] = params.get("status", {}).get("type") == "active"
            elif method == "thread/name/updated" and params.get("threadName"):
                title = " ".join(params["threadName"].split())
                state["title"] = title[:48] + ("…" if len(title) > 48 else "")
            elif method == "turn/started":
                state["active"] = True
            elif method in ("turn/completed", "thread/closed"):
                state["active"] = False
            elif method == "thread/tokenUsage/updated":
                self._record_usage(state, params.get("tokenUsage", {}))

    def flush(self):
        with self._lock:
            now = self._clock()
            for state in self._threads.values():
                while (state["samples"] and state["samples"][0][0] <= now - WINDOW_SECONDS
                       and self._sample_tps(state["samples"][0], now) < 1e-6):
                    state["samples"].popleft()

    def _sample_tps(self, sample, now):
        age = max(0.0, now - sample[0])
        rate = sample[1] / WINDOW_SECONDS
        if self._smoothing_seconds <= 0:
            return rate if age < WINDOW_SECONDS else 0.0
        # Exact exponential smoothing of this sample's five-second rate pulse.
        # Evaluating by elapsed time makes the result independent of UI reads
        # and listener delays, including when a sample leaves the raw window.
        rise = -math.expm1(-min(age, WINDOW_SECONDS) / self._smoothing_seconds)
        decay = math.exp(-max(0.0, age - WINDOW_SECONDS) / self._smoothing_seconds)
        return rate * rise * decay

    def _record_usage(self, state, usage):
        if not isinstance(usage, dict) or not isinstance(usage.get("total"), dict):
            return
        total = usage.get("total", {}).get("outputTokens")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            return
        previous = state["usage_total"]
        state["usage_total"] = total
        # The first event establishes a baseline, including after reconnect.
        # A lower counter starts a new baseline rather than negative output.
        if previous is not None and total > previous:
            # outputTokens already includes reasoning and generated tool calls.
            # Never add reasoningOutputTokens again or mix in streamed text.
            state["samples"].append((self._clock(), total - previous))

    def retain_threads(self, loaded):
        with self._lock:
            needed = set(loaded) | {tid for tid, state in self._threads.items() if state["samples"]}
            # Keep ancestor metadata while a descendant is loaded or fading out.
            for thread_id in list(needed):
                while thread_id in self._threads:
                    parent = self._threads[thread_id]["parent_id"]
                    if not parent or parent in needed:
                        break
                    needed.add(parent)
                    thread_id = parent
            for thread_id, state in list(self._threads.items()):
                if thread_id not in loaded:
                    state["active"] = False
                if thread_id not in needed:
                    del self._threads[thread_id]

    def missing_parent_ids(self):
        with self._lock:
            return {state["parent_id"] for state in self._threads.values()
                    if state["parent_id"] and not self._threads.get(state["parent_id"], {}).get("metadata_loaded")}

    def _root_thread_id(self, thread_id):
        seen = set()
        while thread_id in self._threads:
            seen.add(thread_id)
            parent = self._threads[thread_id]["parent_id"]
            if not parent or parent in seen:
                break
            thread_id = parent
        return thread_id

    def snapshot(self):
        with self._lock:
            now = self._clock()
            groups = {}
            for thread_id, state in self._threads.items():
                root = self._root_thread_id(thread_id)
                group = groups.setdefault(root, {
                    "id": root, "title": self._threads.get(root, {}).get("title", root),
                    "tps": 0.0, "active": False,
                })
                group["tps"] += sum(self._sample_tps(sample, now) for sample in state["samples"])
                group["active"] |= state["active"]
            rows = []
            for group in groups.values():
                rate = group["tps"]
                if rate < ZERO_TPS:
                    rate = 0.0
                if group["active"] or rate:
                    rows.append({"id": group["id"], "title": group["title"], "tps": rate})
            rows.sort(key=lambda row: (row["title"], row["id"]))
            return {"connected": self.connected,
                    "total_tps": sum(row["tps"] for row in rows) if self.connected else None,
                    "threads": rows if self.connected else []}


class CodexTpsMonitor:
    """Observe the existing desktop daemon over a local Unix WebSocket."""

    def __init__(self, socket_path=None):
        self._socket_path = str(socket_path or Path.home() / ".codex/app-server-control/app-server-control.sock")
        self.error = None
        self._stop = threading.Event()
        self._connection = None
        self._worker = None
        self._tracker = None
        self._request_id = 0

    def start(self):
        self._worker = threading.Thread(target=self._run, name="codex-tps", daemon=True)
        self._worker.start()

    def stop(self):
        self._stop.set()
        connection = self._connection
        if connection is not None:
            connection.close()
        if self._worker is not None:
            self._worker.join(timeout=2)

    def snapshot(self):
        tracker = self._tracker
        return tracker.snapshot() if tracker else {"connected": False, "total_tps": None, "threads": []}

    def _run(self):
        self._tracker = TpsTracker()
        delay = 1
        while not self._stop.is_set():
            try:
                self._listen()
                delay = 1
            except Exception as error:
                self.error = str(error)
                logging.getLogger(__name__).debug("Codex TPS disconnected: %s", error)
            finally:
                self._tracker.reset()
                connection, self._connection = self._connection, None
                if connection is not None:
                    connection.close()
            if self._stop.wait(delay):
                break
            delay = min(delay * 2, 30)

    def _read(self, timeout):
        try:
            message = json.loads(self._connection.recv(timeout=timeout))
            return message if isinstance(message, dict) else None
        except TimeoutError:
            return None

    def _rpc(self, method, params):
        self._request_id += 1
        request_id = self._request_id
        self._connection.send(json.dumps({"id": request_id, "method": method, "params": params}))
        deadline = time.monotonic() + 7
        while not self._stop.is_set() and time.monotonic() < deadline:
            message = self._read(0.25)
            if message is None:
                continue
            if message.get("id") == request_id:
                return message
            self._tracker.handle(message)
        raise RuntimeError("Codex observer request timed out")

    def _listen(self):
        from websockets.sync.client import unix_connect

        # AF_UNIX transport cannot contact a remote endpoint or start a backend.
        self._connection = unix_connect(
            self._socket_path, uri="ws://localhost/rpc", legacy=True,
            open_timeout=3, close_timeout=1, compression=None, max_size=64 * 1024 * 1024,
        )
        response = self._rpc("initialize", {
            "clientInfo": {"name": "work_intensity_tps", "version": "0.1.0"},
            "capabilities": {"experimentalApi": True, "optOutNotificationMethods": [
                "item/agentMessage/delta",
                "item/commandExecution/outputDelta", "item/reasoning/textDelta",
                "item/reasoning/summaryTextDelta", "item/reasoning/summaryPartAdded",
                "item/fileChange/outputDelta",
            ]},
        })
        if "error" in response:
            raise RuntimeError("Codex event initialization failed")
        self._connection.send(json.dumps({"method": "initialized", "params": {}}))
        subscribed = set()
        next_discovery = next_flush = 0
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_discovery:
                loaded, cursor = set(), None
                while True:
                    response = self._rpc("thread/loaded/list", {"limit": 100, "cursor": cursor})
                    if "error" in response:
                        raise RuntimeError("Cannot list desktop conversations")
                    result = response["result"]
                    loaded.update(result["data"])
                    cursor = result.get("nextCursor")
                    if not cursor:
                        break
                self._tracker.retain_threads(loaded)
                subscribed.intersection_update(loaded)
                for thread_id in sorted(loaded - subscribed):
                    response = self._rpc("thread/resume", {"threadId": thread_id, "excludeTurns": True})
                    if "error" not in response:
                        self._tracker.update_thread(response["result"]["thread"])
                        subscribed.add(thread_id)
                attempted = set()
                while parents := self._tracker.missing_parent_ids() - attempted:
                    for parent in sorted(parents):
                        attempted.add(parent)
                        response = self._rpc("thread/read", {"threadId": parent, "includeTurns": False})
                        if "error" not in response:
                            self._tracker.update_thread(response["result"]["thread"])
                self._tracker.connected = True
                self.error = None
                next_discovery = time.monotonic() + 5
            if now >= next_flush:
                self._tracker.flush()
                next_flush = now + 1
            message = self._read(0.2)
            if message is not None:
                self._tracker.handle(message)
