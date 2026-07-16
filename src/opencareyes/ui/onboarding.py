"""Pet-first first-run welcome dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from opencareyes.ui.widgets import Card, set_accessible
from opencareyes.ui.companion_pages import FerretPreview


class OnboardingDialog(QDialog):
    """A sub-minute setup flow; changes are committed only on completion."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller = controller
        self.setObjectName("onboardingDialog")
        self.setWindowTitle("欢迎使用 OpenCareEyes")
        self.setModal(True)
        self.setMinimumSize(640, 480)
        self.resize(720, 520)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self._build_ui()
        failed = getattr(self._controller, "operation_failed", None)
        if failed is not None:
            failed.connect(self._show_error)
        self._update_navigation()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(18)

        brand = QLabel("OpenCareEyes")
        brand.setObjectName("brandTitle")
        root.addWidget(brand)
        self._step_label = QLabel()
        self._step_label.setObjectName("stepLabel")
        root.addWidget(self._step_label)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._companion_step())
        self._stack.addWidget(self._display_step())
        self._stack.addWidget(self._break_step())
        self._stack.addWidget(self._automation_step())
        self._stack.currentChanged.connect(self._update_navigation)
        root.addWidget(self._stack, 1)

        navigation = QHBoxLayout()
        self._back_button = QPushButton("上一步")
        self._back_button.setObjectName("quietButton")
        self._back_button.clicked.connect(
            lambda: self._stack.setCurrentIndex(self._stack.currentIndex() - 1)
        )
        self._next_button = QPushButton("下一步")
        self._next_button.setObjectName("primaryButton")
        self._next_button.clicked.connect(self._advance)
        set_accessible(self._back_button, "返回上一步")
        set_accessible(self._next_button, "进入下一步")
        navigation.addStretch()
        navigation.addWidget(self._back_button)
        navigation.addWidget(self._next_button)

        self._error_label = QLabel()
        self._error_label.setObjectName("messageBanner")
        self._error_label.setProperty("kind", "error")
        self._error_label.setWordWrap(True)
        self._error_label.setAccessibleName("首次设置错误提示")
        self._error_label.hide()
        root.addWidget(self._error_label)
        root.addLayout(navigation)

    def _companion_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("先认识你的桌面伙伴")
        title.setObjectName("onboardingTitle")
        description = QLabel("鼬鼬会在桌面陪伴、提示休息，并帮你打开常用工具。")
        description.setObjectName("pageDescription")
        layout.addWidget(title)
        layout.addWidget(description)

        card = Card()
        row = QHBoxLayout()
        preview = FerretPreview()
        preview.setMinimumSize(220, 180)
        row.addWidget(preview, 3)
        copy = QVBoxLayout()
        name = QLabel("鼬鼬 · 白鼬")
        name.setObjectName("statusValue")
        detail = QLabel("可拖动、可隐藏；锁屏、全屏和睡眠时会安静退场。")
        detail.setWordWrap(True)
        self._pet_toggle = QCheckBox("完成后在桌面显示鼬鼬（推荐）")
        self._pet_toggle.setChecked(True)
        self._pet_toggle.setToolTip("可随时从托盘显示或隐藏")
        set_accessible(
            self._pet_toggle,
            "显示桌面伙伴",
            "完成设置后在桌面右下角显示可互动、可拖动的鼬鼬伙伴",
        )
        copy.addWidget(name)
        copy.addWidget(detail)
        copy.addStretch()
        copy.addWidget(self._pet_toggle)
        row.addLayout(copy, 2)
        card.body.addLayout(row)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _display_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("先选择一个舒适的显示方案")
        title.setObjectName("onboardingTitle")
        description = QLabel("稍后可随时调整。方案只影响色温与调暗强度。")
        description.setObjectName("pageDescription")
        layout.addWidget(title)
        layout.addWidget(description)

        card = Card()
        self._profile_group = QButtonGroup(self)
        options = QHBoxLayout()
        for key, label, detail in (
            ("office", "办公", "自然清晰"),
            ("reading", "阅读", "柔和偏暖"),
            ("night", "夜间", "暖色调暗"),
            ("game", "游戏", "保持清爽"),
        ):
            choice = QRadioButton(f"{label}\n{detail}")
            choice.setObjectName("choiceButton")
            choice.setProperty("profile", key)
            choice.setMinimumHeight(82)
            set_accessible(choice, f"{label}显示方案，{detail}")
            self._profile_group.addButton(choice)
            options.addWidget(choice)
            if key == "office":
                choice.setChecked(True)
        card.body.addLayout(options)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _break_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("选择适合你的休息节奏")
        title.setObjectName("onboardingTitle")
        description = QLabel("默认使用温和提醒，不会突然锁定屏幕。")
        description.setObjectName("pageDescription")
        layout.addWidget(title)
        layout.addWidget(description)

        card = Card()
        self._break_group = QButtonGroup(self)
        options = QHBoxLayout()
        for key, label, detail in (
            ("20-20-20", "20-20-20", "每 20 分钟远眺 20 秒"),
            ("pomodoro", "番茄钟", "专注 25 分钟，休息 5 分钟"),
            ("balanced", "平衡节奏", "短休息 + 每小时长休息"),
            ("custom", "暂不启用", "以后在休息节奏中设置"),
        ):
            choice = QRadioButton(f"{label}\n{detail}")
            choice.setObjectName("choiceButton")
            choice.setProperty("mode", key)
            choice.setMinimumHeight(92)
            set_accessible(choice, f"{label}，{detail}")
            self._break_group.addButton(choice)
            options.addWidget(choice)
            if key == "20-20-20":
                choice.setChecked(True)
        card.body.addLayout(options)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _automation_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("最后，让它自动运行")
        title.setObjectName("onboardingTitle")
        description = QLabel("这些选项都可稍后修改。位置只保存在本机。")
        description.setObjectName("pageDescription")
        layout.addWidget(title)
        layout.addWidget(description)

        card = Card()
        self._autostart_toggle = QCheckBox("登录 Windows 后自动启动")
        self._autostart_toggle.setChecked(True)
        self._automation_toggle = QCheckBox("按日出日落自动切换显示方案")
        self._city_combo = QComboBox()
        self._city_combo.addItem("请选择城市", None)
        for city, coordinates in (
            ("北京", (39.9042, 116.4074)),
            ("上海", (31.2304, 121.4737)),
            ("广州", (23.1291, 113.2644)),
            ("深圳", (22.5431, 114.0579)),
            ("成都", (30.5728, 104.0668)),
            ("济南", (36.6512, 117.1201)),
        ):
            self._city_combo.addItem(city, coordinates)
        self._city_combo.setEnabled(False)
        self._automation_toggle.toggled.connect(self._city_combo.setEnabled)
        set_accessible(self._autostart_toggle, "开机自动启动")
        set_accessible(self._automation_toggle, "按日出日落自动切换")
        set_accessible(self._city_combo, "选择城市")
        card.body.addWidget(self._autostart_toggle)
        card.body.addWidget(self._automation_toggle)
        card.body.addWidget(self._city_combo)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _update_navigation(self, *_args) -> None:
        index = self._stack.currentIndex()
        self._step_label.setText(f"步骤 {index + 1} / {self._stack.count()}")
        self._back_button.setVisible(index > 0)
        last = index == self._stack.count() - 1
        self._next_button.setText("完成设置" if last else "下一步")
        self._next_button.setAccessibleName("完成首次设置" if last else "进入下一步")

    def _advance(self) -> None:
        if self._stack.currentIndex() < self._stack.count() - 1:
            self._stack.setCurrentIndex(self._stack.currentIndex() + 1)
            return
        if self._automation_toggle.isChecked() and self._city_combo.currentData() is None:
            self._city_combo.setFocus()
            self._city_combo.setToolTip("请先选择城市")
            self._city_combo.showPopup()
            return
        if self._commit():
            self.accept()

    def _commit(self) -> bool:
        self._error_label.clear()
        self._error_label.hide()

        profile_button = self._profile_group.checkedButton()
        if profile_button is None:
            self._show_error("onboarding_profile", "请选择一个显示方案后重试。")
            return False
        if not self._run_command(
            self._controller.apply_display_profile,
            profile_button.property("profile"),
        ):
            return False

        break_button = self._break_group.checkedButton()
        if break_button is None:
            self._show_error("onboarding_break", "请选择一个休息节奏后重试。")
            return False
        mode = break_button.property("mode")
        display_setter = getattr(
            self._controller,
            "set_break_countdown_display",
            None,
        )
        if callable(display_setter) and not self._run_command(
            display_setter,
            "floating" if self._pet_toggle.isChecked() else "tray",
        ):
            return False
        companion_setter = getattr(
            self._controller,
            "set_companion_enabled",
            None,
        )
        if callable(companion_setter) and not self._run_command(
            companion_setter,
            self._pet_toggle.isChecked(),
        ):
            return False
        if mode == "custom":
            if not self._run_command(
                self._controller.set_feature_enabled,
                "breaks",
                False,
            ):
                return False
        else:
            if not self._run_command(self._controller.set_break_mode, mode):
                return False
            if not self._run_command(
                self._controller.set_feature_enabled,
                "breaks",
                True,
            ):
                return False

        if not self._run_command(
            self._controller.set_autostart,
            self._autostart_toggle.isChecked(),
        ):
            return False
        if self._automation_toggle.isChecked():
            latitude, longitude = self._city_combo.currentData()
            if not self._run_command(
                self._controller.set_schedule,
                True,
                mode="sun",
                latitude=latitude,
                longitude=longitude,
                city=self._city_combo.currentText(),
            ):
                return False
        else:
            if not self._run_command(self._controller.set_schedule, False):
                return False

        complete = getattr(self._controller, "complete_onboarding", None)
        if not callable(complete):
            complete = getattr(self._controller, "mark_onboarding_complete", None)
        if not callable(complete):
            self._show_error("onboarding", "无法保存首次设置，请重试。")
            return False
        return self._run_command(complete)

    def _run_command(self, command, *args, **kwargs) -> bool:
        if command(*args, **kwargs):
            return True
        if self._error_label.isHidden():
            self._show_error("onboarding", "设置未能应用，请检查后重试。")
        return False

    def _show_error(self, _code: str, message: str) -> None:
        self._error_label.setText(f"设置未能完成：{message}")
        self._error_label.show()


# Both names are kept because integration branches used each while v0.2 was built.
WelcomeWizard = OnboardingDialog
