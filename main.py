import multiprocessing
import os
import signal
import subprocess
import sys

_DAEMONIZED_ENV_KEY = "WORKINTENSITY_DAEMONIZED"


def _ensure_required_permissions():
    missing_permissions = []

    try:
        import Quartz
        from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
    except Exception as e:
        raise RuntimeError(f"无法检查 macOS 权限：{e}") from e

    accessibility_granted = bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}))
    input_monitoring_granted = bool(Quartz.CGPreflightListenEventAccess())

    if not input_monitoring_granted:
        input_monitoring_granted = bool(Quartz.CGRequestListenEventAccess())

    if not accessibility_granted:
        missing_permissions.append("辅助功能")
    if not input_monitoring_granted:
        missing_permissions.append("输入监控")

    if missing_permissions:
        raise RuntimeError(
            "缺少必要权限："
            f"{'、'.join(missing_permissions)}。"
            "请打开“系统设置 → 隐私与安全性”。"
            "若缺少“辅助功能”权限，请进入“辅助功能”并勾选当前 Python/终端应用；"
            "若缺少“输入监控”权限，请进入“输入监控”并勾选当前 Python/终端应用；"
            "授权后完全退出并重新启动程序。"
        )


def _detach_from_terminal_if_possible():
    if os.environ.get(_DAEMONIZED_ENV_KEY) == "1":
        return
    if os.environ.get("WORKINTENSITY_FOREGROUND") == "1":
        return

    os.environ[_DAEMONIZED_ENV_KEY] = "1"

    try:
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
    except Exception:
        pass

    script_path = os.path.abspath(__file__)
    cwd = os.path.dirname(script_path)
    env = os.environ.copy()

    try:
        with open(os.devnull, "r") as null_in, open(os.devnull, "a+") as null_out:
            subprocess.Popen(
                [sys.executable, script_path],
                cwd=cwd,
                env=env,
                stdin=null_in,
                stdout=null_out,
                stderr=null_out,
                start_new_session=True,
                close_fds=True,
            )
        os._exit(0)
    except Exception:
        os.environ.pop(_DAEMONIZED_ENV_KEY, None)
        return


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
                import AppKit
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
                try:
                    symbol_config = AppKit.NSImageSymbolConfiguration.configurationWithPointSize_weight_scale_(
                        18, AppKit.NSFontWeightSemibold, AppKit.NSImageSymbolScaleMedium
                    )
                    image = image.imageWithSymbolConfiguration_(symbol_config)
                except Exception:
                    pass

                try:
                    thickness = float(AppKit.NSStatusBar.systemStatusBar().thickness())
                    image.setSize_((max(0.0, thickness - 2.0), max(0.0, thickness - 2.0)))
                except Exception:
                    image.setSize_((20, 20))
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
    _ensure_required_permissions()
    _detach_from_terminal_if_possible()
    main()
