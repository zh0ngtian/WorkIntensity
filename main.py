import multiprocessing
import time

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


if __name__ == "__main__":
    app = WorkIntensityStatusBarApp()
    app.run()
