import multiprocessing
import os
import signal
import sys
import time

_DAEMONIZED_ENV_KEY = "WORKINTENSITY_DAEMONIZED"


def _detach_from_terminal_if_possible():
    if os.environ.get(_DAEMONIZED_ENV_KEY) == "1":
        return
    if os.environ.get("WORKINTENSITY_FOREGROUND") == "1":
        return
    if not hasattr(os, "fork"):
        return

    os.environ[_DAEMONIZED_ENV_KEY] = "1"

    try:
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
    except Exception:
        pass

    try:
        pid = os.fork()
        if pid > 0:
            os._exit(0)
    except OSError:
        return

    try:
        os.setsid()
    except Exception:
        pass

    try:
        pid = os.fork()
        if pid > 0:
            os._exit(0)
    except OSError:
        return

    try:
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass

    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass

    try:
        with open(os.devnull, "r") as null_in:
            os.dup2(null_in.fileno(), sys.stdin.fileno())
        with open(os.devnull, "a+") as null_out:
            os.dup2(null_out.fileno(), sys.stdout.fileno())
            os.dup2(null_out.fileno(), sys.stderr.fileno())
    except Exception:
        pass


def main():
    import rumps

    import plot
    import record

    class WorkIntensityStatusBarApp(rumps.App):
        def __init__(self):
            super(WorkIntensityStatusBarApp, self).__init__("WorkIntensity", title=None)
            self._set_status_bar_symbol_icon()

            self.recorder = record.InputRecorder()
            self.recorder.start()

        def __del__(self):
            self.recorder.stop()

        def _set_status_bar_symbol_icon(self):
            try:
                from AppKit import NSImage
            except Exception:
                return

            symbol_candidates = [
                # "chart.bar.fill",
                "chart.bar.xaxis",
            ]

            for symbol_name in symbol_candidates:
                image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol_name, None)
                if image is None:
                    continue
                image.setSize_((18, 18))
                image.setTemplate_(True)
                self._icon = f"sf-symbol:{symbol_name}"
                self._icon_nsimage = image
                return

        @rumps.clicked("Plot")
        def plot_button(self, _):
            p = multiprocessing.Process(target=plot.plot_fig)
            p.start()
            p.join()

    app = WorkIntensityStatusBarApp()
    app.run()


if __name__ == "__main__":
    _detach_from_terminal_if_possible()
    main()
