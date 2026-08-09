import multiprocessing
import os
import signal
import subprocess
import sys
from datetime import datetime

_DAEMONIZED_ENV_KEY = "WORKINTENSITY_DAEMONIZED"


def _build_status_title(now, storage, format_token_count, get_quota_status):
    try:
        today_seconds = storage.get_activity_seconds_for_date(now)
        work_hours_title = f"{len(today_seconds) / 100:.1f}h"
    except Exception:
        work_hours_title = "--h"

    try:
        day_key = now.strftime("%Y-%m-%d")
        token_usage_by_day = storage.get_token_usage_by_date_range(now, now)
        today_tokens = sum(token_usage_by_day.get(day_key, []))
        token_title = format_token_count(today_tokens)
    except Exception:
        token_title = "--"

    try:
        quota_title = get_quota_status(now)
    except Exception:
        quota_title = "--% · --"

    return f"{work_hours_title} · {token_title} · {quota_title}"


def _show_error_dialog(message):
    title = "WorkIntensity 权限错误"
    apple_script = f'display alert "{title.replace(chr(34), chr(92) + chr(34))}" message "{message.replace(chr(34), chr(92) + chr(34))}" as critical'
    try:
        subprocess.run(["osascript", "-e", apple_script], check=False)
    except Exception:
        print(message, file=sys.stderr)


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
            f"{'、'.join(missing_permissions)}。\n"
            "请打开「系统设置 → 隐私与安全性」。\n\n"
            "若缺少「辅助功能」权限，请进入「辅助功能」并勾选当前终端应用；\n\n"
            "若缺少「输入监控」权限，请进入「输入监控」并勾选当前终端应用；\n\n"
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

    import codex_quota
    import plot
    import record
    import storage

    STATUS_REFRESH_SECONDS = 10 * 60
    STATUS_TITLE_FONT_SIZE = 14

    class WorkIntensityStatusBarApp(rumps.App):
        def __init__(self):
            super(WorkIntensityStatusBarApp, self).__init__("WorkIntensity", title="0.0h")
            self._set_status_bar_symbol_icon()
            self._update_status_title()
            rumps.events.before_start.register(self._update_status_title)
            self._status_refresh_timer = rumps.Timer(self._update_status_title, STATUS_REFRESH_SECONDS)
            self._status_refresh_timer.start()

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

        def _update_status_title(self, _=None):
            title = _build_status_title(
                datetime.now(),
                storage,
                plot.format_token_count,
                codex_quota.fetch_quota_status,
            )
            self.title = title
            self._set_status_bar_title_font(title)

        def _set_status_bar_title_font(self, title):
            try:
                import AppKit

                font = AppKit.NSFont.systemFontOfSize_(STATUS_TITLE_FONT_SIZE)
                attributes = {AppKit.NSFontAttributeName: font}
                attributed_title = AppKit.NSAttributedString.alloc().initWithString_attributes_(title, attributes)
                self._nsapp.nsstatusitem.button().setAttributedTitle_(attributed_title)
            except Exception:
                pass

        @rumps.clicked("Plot")
        def plot_button(self, _):
            p = multiprocessing.Process(target=plot.plot_fig)
            p.start()

    app = WorkIntensityStatusBarApp()
    app.run()


if __name__ == "__main__":
    try:
        _ensure_required_permissions()
        _detach_from_terminal_if_possible()
        main()
    except RuntimeError as e:
        _show_error_dialog(str(e))
        sys.exit(1)
