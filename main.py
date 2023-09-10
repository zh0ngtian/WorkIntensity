import multiprocessing
import time

import rumps

import plot
import record


class WorkDensityStatusBarApp(rumps.App):
    def __init__(self):
        super(WorkDensityStatusBarApp, self).__init__("WorkDensity", title="WorkDensity")

        self.recorder = record.InputRecorder()

    @rumps.clicked("Start")
    def start_button(self, _):
        self.recorder.start()

    @rumps.clicked("Stop")
    def stop_button(self, _):
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
