import multiprocessing
import os
import threading
import time

import pygetwindow as gw
from pynput import keyboard, mouse

import storage

event_lock = threading.Lock()


def _ensure_log_dir():
    os.makedirs("log", exist_ok=True)


def _write_record_error(message):
    try:
        _ensure_log_dir()
        with open("log/record_error.log", "a+", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except Exception:
        pass


# 监听鼠标点击事件
def on_mouse_click(x, y, button, pressed):
    try:
        with event_lock:
            storage.record_activity()
    except Exception as e:
        _write_record_error(f"on_mouse_click error: {e!r}")


# 监听鼠标滚动事件
def on_mouse_scroll(x, y, dx, dy):
    try:
        with event_lock:
            storage.record_activity()
    except Exception as e:
        _write_record_error(f"on_mouse_scroll error: {e!r}")


# 监听键盘事件
def on_key_press(key):
    try:
        with event_lock:
            storage.record_activity()
    except Exception as e:
        _write_record_error(f"on_key_press error: {e!r}")


# 监听飞书会议
def on_feishu_meeting():
    while True:
        try:
            active_window = gw.getActiveWindow()
            title = getattr(active_window, "title", None)
            active_window_name = title if isinstance(title, str) else (str(active_window) if active_window else "")
            if active_window_name.strip() == "Window Server":
                with event_lock:
                    storage.record_activity()
        except Exception as e:
            _write_record_error(f"on_feishu_meeting error: {e!r}")

        time.sleep(10)


class InputRecorder:
    def __init__(self):
        self._is_recording = False
        self.mouse_listener = None
        self.keyboard_listener = None
        self.feishu_meeting_monitor = None

    def start(self):
        if not self._is_recording:
            self._is_recording = True

            self.mouse_listener = mouse.Listener(on_click=on_mouse_click, on_scroll=on_mouse_scroll)
            self.keyboard_listener = keyboard.Listener(on_press=on_key_press)
            self.feishu_meeting_monitor = multiprocessing.Process(target=on_feishu_meeting)

            self.mouse_listener.start()
            time.sleep(1)
            self.keyboard_listener.start()
            self.feishu_meeting_monitor.start()

    def stop(self):
        if self._is_recording:
            self._is_recording = False

            try:
                if self.mouse_listener is not None:
                    self.mouse_listener.stop()
            except Exception as e:
                _write_record_error(f"mouse_listener.stop error: {e!r}")

            try:
                if self.keyboard_listener is not None:
                    self.keyboard_listener.stop()
            except Exception as e:
                _write_record_error(f"keyboard_listener.stop error: {e!r}")

            try:
                if self.feishu_meeting_monitor is not None:
                    self.feishu_meeting_monitor.terminate()
                    self.feishu_meeting_monitor.join(timeout=2)
            except Exception as e:
                _write_record_error(f"feishu_meeting_monitor stop error: {e!r}")


if __name__ == "__main__":
    ir = InputRecorder()
    ir.start()
    ir.mouse_listener.join()
    ir.keyboard_listener.join()
