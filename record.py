import multiprocessing
import os
import threading
import time

import pygetwindow as gw
from pynput import keyboard, mouse

event_lock = threading.Lock()
event_log_file = None


def open_log_file():
    global event_log_file

    file_path = f'log/{time.strftime("%Y-%m-%d")}.log'

    if event_log_file == None:
        if not os.path.exists("log"):
            os.makedirs("log", exist_ok=False)
        event_log_file = open(file_path, "a+")

    if event_log_file.name != file_path:
        event_log_file.close()
        event_log_file = open(file_path, "a+")

    return event_log_file


def get_current_timestamp():
    return time.strftime("%H:%M:%S")


# 监听鼠标点击事件
def on_mouse_click(x, y, button, pressed):
    with event_lock:
        event_log_file = open_log_file()
        event_log_file.write(f"[{get_current_timestamp()}] mouse click\n")
        event_log_file.flush()


# 监听鼠标滚动事件
def on_mouse_scroll(x, y, dx, dy):
    with event_lock:
        event_log_file = open_log_file()
        event_log_file.write(f"[{get_current_timestamp()}] mouse scroll\n")
        event_log_file.flush()


# 监听键盘事件
def on_key_press(key):
    with event_lock:
        event_log_file = open_log_file()
        event_log_file.write(f"[{get_current_timestamp()}] key press\n")
        event_log_file.flush()


# 监听飞书会议
def on_feishu_meeting():
    while True:
        with event_lock:
            active_window_name = gw.getActiveWindow()
            if active_window_name.strip() == "Window Server":
                event_log_file = open_log_file()
                event_log_file.write(f"[{get_current_timestamp()}] feishu meeting\n")
                event_log_file.flush()
            time.sleep(1)


class InputRecorder:
    def __init__(self):
        self._is_recording = False
        self.mouse_listener = None
        self.keyboard_listener = None
        self.feishu_meeting_monitor = multiprocessing.Process(target=on_feishu_meeting)

    def start(self):
        if not self._is_recording:
            self._is_recording = True

            self.mouse_listener = mouse.Listener(on_click=on_mouse_click, on_scroll=on_mouse_scroll)
            self.keyboard_listener = keyboard.Listener(on_press=on_key_press)

            self.mouse_listener.start()
            time.sleep(1)
            self.keyboard_listener.start()
            self.feishu_meeting_monitor.start()

    def stop(self):
        if self._is_recording:
            self._is_recording = False

            self.mouse_listener.stop()
            self.keyboard_listener.stop()
            self.feishu_meeting_monitor.stop()


if __name__ == "__main__":
    ir = InputRecorder()
    ir.start()
    ir.mouse_listener.join()
    ir.keyboard_listener.join()
