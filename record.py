import multiprocessing
import os
import threading
import time

import pygetwindow as gw
from pynput import keyboard, mouse

event_lock = threading.Lock()
event_log_file = None


def _ensure_log_dir():
    os.makedirs("log", exist_ok=True)


def _write_record_error(message):
    try:
        _ensure_log_dir()
        with open("log/record_error.log", "a+", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except Exception:
        pass


def open_log_file():
    global event_log_file

    file_path = f'log/{time.strftime("%Y-%m-%d")}.log'

    if event_log_file == None:
        _ensure_log_dir()
        event_log_file = open(file_path, "a+", buffering=1, encoding="utf-8")

    if event_log_file.name != file_path:
        event_log_file.close()
        event_log_file = open(file_path, "a+", buffering=1, encoding="utf-8")

    return event_log_file


def get_current_timestamp():
    return time.strftime("%H:%M:%S")


# 监听鼠标点击事件
def on_mouse_click(x, y, button, pressed):
    try:
        with event_lock:
            event_log_file = open_log_file()
            event_log_file.write(f"[{get_current_timestamp()}] mouse click\n")
            event_log_file.flush()
    except Exception as e:
        _write_record_error(f"on_mouse_click error: {e!r}")


# 监听鼠标滚动事件
def on_mouse_scroll(x, y, dx, dy):
    try:
        with event_lock:
            event_log_file = open_log_file()
            event_log_file.write(f"[{get_current_timestamp()}] mouse scroll\n")
            event_log_file.flush()
    except Exception as e:
        _write_record_error(f"on_mouse_scroll error: {e!r}")


# 监听键盘事件
def on_key_press(key):
    try:
        with event_lock:
            event_log_file = open_log_file()
            event_log_file.write(f"[{get_current_timestamp()}] key press\n")
            event_log_file.flush()
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
                    event_log_file = open_log_file()
                    event_log_file.write(f"[{get_current_timestamp()}] feishu meeting\n")
                    event_log_file.flush()
        except Exception as e:
            _write_record_error(f"on_feishu_meeting error: {e!r}")

        time.sleep(10)


class InputRecorder:
    def __init__(self):
        self._is_recording = False
        self.mouse_listener = None
        self.keyboard_listener = None
        self.feishu_meeting_monitor = None
        self._flush_stop_event = threading.Event()
        self._flush_thread = None

    def start(self):
        if not self._is_recording:
            self._is_recording = True
            self._flush_stop_event.clear()

            self.mouse_listener = mouse.Listener(on_click=on_mouse_click, on_scroll=on_mouse_scroll)
            self.keyboard_listener = keyboard.Listener(on_press=on_key_press)
            self.feishu_meeting_monitor = multiprocessing.Process(target=on_feishu_meeting)

            self.mouse_listener.start()
            time.sleep(1)
            self.keyboard_listener.start()
            self.feishu_meeting_monitor.start()
            self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
            self._flush_thread.start()

    def stop(self):
        if self._is_recording:
            self._is_recording = False
            self._flush_stop_event.set()

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

            try:
                if self._flush_thread is not None:
                    self._flush_thread.join(timeout=2)
            except Exception as e:
                _write_record_error(f"flush_thread.join error: {e!r}")

    def _flush_loop(self):
        while not self._flush_stop_event.is_set():
            try:
                with event_lock:
                    if event_log_file is not None:
                        event_log_file.flush()
                        os.fsync(event_log_file.fileno())
            except Exception as e:
                _write_record_error(f"flush_loop error: {e!r}")
            time.sleep(2)


if __name__ == "__main__":
    ir = InputRecorder()
    ir.start()
    ir.mouse_listener.join()
    ir.keyboard_listener.join()
