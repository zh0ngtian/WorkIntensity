"""Native macOS preferences for status bar visibility."""

import AppKit
import objc


_FIELD_ROWS = (
    ("work_hours", "今日工作时长", "3.2h"),
    ("tokens", "今日 Token 用量", "1.2K"),
    ("quota_remaining", "Codex 剩余额度百分比", "82%"),
    ("quota_reset", "额度重置倒计时与剩余时间百分比", "2d20h(40%)"),
)


class StatusBarSettingsWindow(AppKit.NSObject):
    @objc.python_method
    def configure(self, storage, on_change):
        self._storage = storage
        self._on_change = on_change
        self._checkboxes = {}
        self._selected_fields = ()
        self._window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0, 0), (520, 350)),
            AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self._window.setTitle_("WorkIntensity 设置")
        self._window.setReleasedWhenClosed_(False)
        self._window.center()
        content = self._window.contentView()

        heading = self._label("状态栏显示内容", (28, 297, 464, 26), 17)
        heading.setFont_(AppKit.NSFont.boldSystemFontOfSize_(17))
        content.addSubview_(heading)
        content.addSubview_(self._label("选择需要显示的内容，修改后立即生效。", (28, 269, 464, 22), 13, True))

        for index, (field, title, example) in enumerate(_FIELD_ROWS):
            y = 218 - index * 38
            checkbox = AppKit.NSButton.checkboxWithTitle_target_action_(title, self, "toggleField:")
            checkbox.setFrame_(((28, y), (330, 26)))
            checkbox.setFont_(AppKit.NSFont.systemFontOfSize_(13))
            content.addSubview_(checkbox)
            self._checkboxes[field] = checkbox
            example_label = self._label(example, (366, y + 2, 126, 22), 13, True)
            example_label.setAlignment_(AppKit.NSTextAlignmentRight)
            content.addSubview_(example_label)

        content.addSubview_(self._label("设置自动保存在本机，全部取消时仅显示状态栏图标。", (28, 38, 464, 22), 12, True))

    @objc.python_method
    def _label(self, text, frame, size, secondary=False):
        label = AppKit.NSTextField.labelWithString_(text)
        x, y, width, height = frame
        label.setFrame_(((x, y), (width, height)))
        label.setFont_(AppKit.NSFont.systemFontOfSize_(size))
        if secondary:
            label.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        return label

    @objc.python_method
    def _set_selected_fields(self, fields):
        self._selected_fields = fields
        for field, checkbox in self._checkboxes.items():
            checkbox.setState_(AppKit.NSControlStateValueOn if field in fields else AppKit.NSControlStateValueOff)

    @objc.python_method
    def show(self):
        try:
            self._set_selected_fields(self._storage.get_status_bar_fields())
        except Exception as error:
            self._show_error("无法读取设置", error)
            return
        self._window.makeKeyAndOrderFront_(None)
        AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def toggleField_(self, sender):
        fields = tuple(
            field for field, checkbox in self._checkboxes.items()
            if checkbox.state() == AppKit.NSControlStateValueOn
        )
        try:
            saved_fields = self._storage.set_status_bar_fields(fields)
        except Exception as error:
            self._set_selected_fields(self._selected_fields)
            self._show_error("无法保存设置", error)
            return
        self._set_selected_fields(saved_fields)
        self._on_change(saved_fields)

    @objc.python_method
    def _show_error(self, title, error):
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(str(error))
        alert.addButtonWithTitle_("好")
        alert.runModal()
