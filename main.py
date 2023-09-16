import multiprocessing
import time

import rumps

import plot
import record


class WorkIntensityStatusBarApp(rumps.App):
    def __init__(self):
        super(WorkIntensityStatusBarApp, self).__init__("WorkIntensity", title="WorkIntensity")

        self.recorder = record.InputRecorder()
        self.recorder.start()

    def __del__(self):
        self.recorder.stop()

    @rumps.clicked("Plot")
    def plot_button(self, _):
        p = multiprocessing.Process(target=plot.plot_fig)
        p.start()
        p.join()


if __name__ == "__main__":
    app = WorkIntensityStatusBarApp()
    app.run()
