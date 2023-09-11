import multiprocessing
import time

import rumps

import plot
import record


class WorkDensityStatusBarApp(rumps.App):
    def __init__(self):
        super(WorkDensityStatusBarApp, self).__init__("WorkDensity", title="WorkDensity")

        self.recorder = record.InputRecorder()
        self.recorder.start()

    def __del__(self):
        self.recorder.stop()

    @rumps.clicked("Plot")
    def plot_button(self, _):
        log_file_path = f'log/{time.strftime("%Y-%m-%d")}.log'
        p = multiprocessing.Process(target=plot.plot_fig, args=[log_file_path])
        p.start()
        p.join()


if __name__ == "__main__":
    app = WorkDensityStatusBarApp()
    app.run()
