'''Companion quick tools kept outside the global application state.'''

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QBoxLayout,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class QuickToolsWindow(QWidget):
    '''A reusable window for private notes, one timer and on-demand system data.'''

    _TOOL_ALIASES = {
        'timer': 'timer',
        'note': 'notes',
        'notes': 'notes',
        'status': 'system',
        'system': 'system',
        'more': 'more',
    }

    def __init__(
        self,
        *,
        timer_service: Any,
        note_repository: Any,
        metrics_service: Any,
        recycle_bin_service: Any,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.Window)
        self.setObjectName('quickToolsWindow')
        self.setWindowTitle('OpenCareEyes 快捷工具')
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setMinimumSize(360, 300)
        self.resize(620, 480)

        self._timer_service = timer_service
        self._note_repository = note_repository
        self._metrics_service = metrics_service
        self._recycle_bin_service = recycle_bin_service
        self._selected_note_id: str | None = None
        self._page_scrolls: list[QScrollArea] = []

        root = QVBoxLayout(self)
        self._root_layout = root
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel('快捷工具')
        title.setObjectName('quickToolsTitle')
        title.setAccessibleName('快捷工具标题')
        root.addWidget(title)

        self.notice_label = QLabel('')
        self.notice_label.setObjectName('quickToolsNotice')
        self.notice_label.setWordWrap(True)
        self.notice_label.setAccessibleName('操作结果')
        self.notice_label.hide()
        root.addWidget(self.notice_label)

        self.tabs = QTabWidget()
        self.tabs.setAccessibleName('快捷工具分类')
        self.tabs.addTab(self._scrollable_page(self._build_timer_page()), '倒计时')
        self.tabs.addTab(self._scrollable_page(self._build_notes_page()), '便签')
        self.tabs.addTab(self._scrollable_page(self._build_system_page()), '系统状态')
        self.tabs.addTab(self._scrollable_page(self._build_more_page()), '更多')
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

        self._time_timer = QTimer(self)
        self._time_timer.setInterval(1_000)
        self._time_timer.timeout.connect(self._refresh_clock)

        self._timer_service.tick.connect(self._on_timer_tick)
        self._timer_service.state_changed.connect(self._on_timer_state)
        self._metrics_service.updated.connect(self._on_metrics_updated)
        self._on_timer_state(self._timer_service.state)
        self._set_style()
        self._fit_to_available_geometry()
        self._update_responsive_layout()

    @property
    def active_tool(self) -> str:
        return ('timer', 'notes', 'system', 'more')[self.tabs.currentIndex()]

    def show_tool(self, tool_id: str) -> None:
        '''Show one tool and keep the same top-level window alive.'''
        normalized = self._TOOL_ALIASES.get(tool_id)
        if normalized is None:
            raise ValueError(f'unknown quick tool: {tool_id}')
        index = ('timer', 'notes', 'system', 'more').index(normalized)
        self.tabs.setCurrentIndex(index)
        if normalized == 'notes':
            self._reload_notes()
        elif normalized == 'more':
            self._refresh_recycle_bin()
        self.show()
        self.raise_()
        self.activateWindow()
        self._sync_metrics_sampling()

    def _scrollable_page(self, content: QWidget) -> QScrollArea:
        content.setMinimumWidth(0)
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        scroll = QScrollArea()
        scroll.setAccessibleName(content.accessibleName())
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(content)
        self._page_scrolls.append(scroll)
        return scroll

    def _build_timer_page(self) -> QWidget:
        page = QWidget()
        page.setAccessibleName('用户倒计时')
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 16, 8, 8)
        layout.setSpacing(12)

        self.timer_display = QLabel('25:00')
        self.timer_display.setObjectName('timerDisplay')
        self.timer_display.setAlignment(Qt.AlignCenter)
        self.timer_display.setAccessibleName('剩余时间')
        layout.addWidget(self.timer_display)

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.timer_label_input = QLineEdit()
        self.timer_label_input.setMaxLength(100)
        self.timer_label_input.setPlaceholderText('例如：背单词（可选）')
        self.timer_label_input.setAccessibleName('倒计时名称')
        form.addRow('名称', self.timer_label_input)

        duration_row = QWidget()
        duration_layout = QHBoxLayout(duration_row)
        duration_layout.setContentsMargins(0, 0, 0, 0)
        self.timer_minutes_input = QSpinBox()
        self.timer_minutes_input.setRange(0, 1_440)
        self.timer_minutes_input.setValue(25)
        self.timer_minutes_input.setSuffix(' 分钟')
        self.timer_minutes_input.setAccessibleName('倒计时分钟')
        self.timer_seconds_input = QSpinBox()
        self.timer_seconds_input.setRange(0, 59)
        self.timer_seconds_input.setSuffix(' 秒')
        self.timer_seconds_input.setAccessibleName('倒计时秒数')
        duration_layout.addWidget(self.timer_minutes_input)
        duration_layout.addWidget(self.timer_seconds_input)
        form.addRow('时长', duration_row)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.timer_start_button = QPushButton('开始')
        self.timer_start_button.setAccessibleName('开始倒计时')
        self.timer_start_button.clicked.connect(self._start_timer)
        self.timer_pause_button = QPushButton('暂停')
        self.timer_pause_button.setAccessibleName('暂停或继续倒计时')
        self.timer_pause_button.clicked.connect(self._toggle_timer_pause)
        self.timer_cancel_button = QPushButton('取消')
        self.timer_cancel_button.setAccessibleName('取消倒计时')
        self.timer_cancel_button.clicked.connect(self._cancel_timer)
        buttons.addWidget(self.timer_start_button)
        buttons.addWidget(self.timer_pause_button)
        buttons.addWidget(self.timer_cancel_button)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return page

    def _build_notes_page(self) -> QWidget:
        page = QWidget()
        page.setAccessibleName('本地便签')
        layout = QHBoxLayout(page)
        self._notes_layout = layout
        layout.setContentsMargins(8, 16, 8, 8)
        layout.setSpacing(12)

        left = QVBoxLayout()
        self.notes_list = QListWidget()
        self.notes_list.setObjectName('notesList')
        self.notes_list.setAccessibleName('便签列表')
        self.notes_list.setMinimumHeight(96)
        self.notes_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.notes_list.currentItemChanged.connect(self._load_selected_note)
        left.addWidget(self.notes_list, 1)
        self.note_new_button = QPushButton('新建')
        self.note_new_button.setAccessibleName('新建便签')
        self.note_new_button.clicked.connect(self._new_note)
        left.addWidget(self.note_new_button)
        layout.addLayout(left, 1)

        editor = QVBoxLayout()
        self.note_title_input = QLineEdit()
        self.note_title_input.setMaxLength(200)
        self.note_title_input.setPlaceholderText('标题（可选）')
        self.note_title_input.setAccessibleName('便签标题')
        self.note_text_input = QTextEdit()
        self.note_text_input.setPlaceholderText('便签仅保存在本机，不进入诊断信息。')
        self.note_text_input.setAccessibleName('便签正文')
        self.note_text_input.setMinimumHeight(120)
        editor.addWidget(self.note_title_input)
        editor.addWidget(self.note_text_input, 1)
        editor_buttons = QHBoxLayout()
        self.note_save_button = QPushButton('保存')
        self.note_save_button.setAccessibleName('保存便签')
        self.note_save_button.clicked.connect(self._save_note)
        self.note_delete_button = QPushButton('删除')
        self.note_delete_button.setAccessibleName('删除当前便签')
        self.note_delete_button.clicked.connect(self._delete_note)
        editor_buttons.addWidget(self.note_save_button)
        editor_buttons.addWidget(self.note_delete_button)
        editor.addLayout(editor_buttons)
        layout.addLayout(editor, 2)
        return page

    def _build_system_page(self) -> QWidget:
        page = QWidget()
        page.setAccessibleName('系统状态')
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 16, 8, 8)
        layout.setSpacing(12)

        self.system_time_label = QLabel('当前时间：--:--:--')
        self.system_time_label.setAccessibleName('当前时间')
        self.cpu_label = QLabel('CPU：正在读取…')
        self.cpu_label.setAccessibleName('CPU 占用')
        self.memory_label = QLabel('内存：正在读取…')
        self.memory_label.setAccessibleName('内存占用')
        self.metrics_status_label = QLabel('仅在此面板可见时读取系统状态。')
        self.metrics_status_label.setWordWrap(True)
        self.metrics_status_label.setAccessibleName('系统状态说明')
        layout.addWidget(self.system_time_label)
        layout.addWidget(self.cpu_label)
        layout.addWidget(self.memory_label)
        layout.addWidget(self.metrics_status_label)
        layout.addStretch(1)
        return page

    def _build_more_page(self) -> QWidget:
        page = QWidget()
        page.setAccessibleName('更多工具')
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 16, 8, 8)
        layout.setSpacing(12)

        card = QFrame()
        card.setObjectName('toolCard')
        card_layout = QVBoxLayout(card)
        heading = QLabel('回收站')
        heading.setObjectName('cardHeading')
        self.recycle_summary_label = QLabel('尚未读取回收站状态。')
        self.recycle_summary_label.setWordWrap(True)
        self.recycle_summary_label.setAccessibleName('回收站项目数量和大小')
        explanation = QLabel('点击后仍会显示 Windows 系统确认；本软件不会跳过确认。')
        explanation.setWordWrap(True)
        explanation.setAccessibleName('回收站安全说明')
        self.recycle_empty_button = QPushButton('查看并清空回收站')
        self.recycle_empty_button.setAccessibleName('查看项目并请求清空回收站')
        self.recycle_empty_button.clicked.connect(self._empty_recycle_bin)
        card_layout.addWidget(heading)
        card_layout.addWidget(self.recycle_summary_label)
        card_layout.addWidget(explanation)
        card_layout.addWidget(self.recycle_empty_button)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _start_timer(self) -> None:
        duration = self.timer_minutes_input.value() * 60 + self.timer_seconds_input.value()
        if duration <= 0:
            self._show_notice('倒计时时长至少为 1 秒。', error=True)
            return
        if duration > 24 * 60 * 60:
            self._show_notice('倒计时时长不能超过 24 小时。', error=True)
            return
        try:
            self._timer_service.start(duration, label=self.timer_label_input.text().strip())
        except (TypeError, ValueError):
            self._show_notice('倒计时参数无效，请重新设置。', error=True)
        except Exception:
            self._show_notice('无法开始倒计时，请稍后重试。', error=True)
        else:
            self._show_notice('倒计时已开始。')

    def _toggle_timer_pause(self) -> None:
        try:
            state = self._timer_service.state
            changed = (
                self._timer_service.pause()
                if state.status == 'running'
                else self._timer_service.resume()
            )
        except Exception:
            self._show_notice('无法更新倒计时状态。', error=True)
            return
        if not changed:
            self._show_notice('当前没有可暂停或继续的倒计时。', error=True)

    def _cancel_timer(self) -> None:
        try:
            changed = self._timer_service.cancel()
        except Exception:
            self._show_notice('无法取消倒计时。', error=True)
            return
        if changed:
            self._show_notice('倒计时已取消。')
        else:
            self._show_notice('当前没有进行中的倒计时。', error=True)

    def _on_timer_tick(self, remaining: int) -> None:
        self.timer_display.setText(_format_duration(remaining))

    def _on_timer_state(self, state: Any) -> None:
        self.timer_display.setText(_format_duration(state.remaining_seconds))
        running = state.status == 'running'
        paused = state.status == 'paused'
        self.timer_pause_button.setEnabled(running or paused)
        self.timer_cancel_button.setEnabled(running or paused)
        self.timer_pause_button.setText('暂停' if running else '继续')
        self.timer_start_button.setText('重新开始' if running or paused else '开始')
        if state.status == 'finished':
            self._show_notice('倒计时完成。')

    def _reload_notes(self, *, select_note_id: str | None = None) -> None:
        try:
            notes = self._note_repository.list_notes()
        except Exception:
            self._show_notice('便签无法读取，请检查本地数据文件。', error=True)
            return
        self.notes_list.blockSignals(True)
        self.notes_list.clear()
        selected_item = None
        for note in notes:
            item = QListWidgetItem(note.title.strip() or '无标题便签')
            item.setData(Qt.UserRole, note.note_id)
            self.notes_list.addItem(item)
            if note.note_id == select_note_id:
                selected_item = item
        self.notes_list.blockSignals(False)
        if selected_item is not None:
            self.notes_list.setCurrentItem(selected_item)
        elif not notes:
            self._new_note()
        else:
            self.notes_list.setCurrentRow(0)

    def _load_selected_note(self, item: QListWidgetItem | None, _previous: Any = None) -> None:
        if item is None:
            return
        note_id = item.data(Qt.UserRole)
        try:
            note = next(
                note
                for note in self._note_repository.list_notes()
                if note.note_id == note_id
            )
        except StopIteration:
            self._show_notice('这条便签已不存在。', error=True)
            self._reload_notes()
            return
        except Exception:
            self._show_notice('便签无法读取。', error=True)
            return
        self._selected_note_id = note.note_id
        self.note_title_input.setText(note.title)
        self.note_text_input.setPlainText(note.text)
        self.note_delete_button.setEnabled(True)

    def _new_note(self) -> None:
        self.notes_list.clearSelection()
        self._selected_note_id = None
        self.note_title_input.clear()
        self.note_text_input.clear()
        self.note_delete_button.setEnabled(False)
        self.note_title_input.setFocus(Qt.OtherFocusReason)

    def _save_note(self) -> None:
        title = self.note_title_input.text()
        text = self.note_text_input.toPlainText()
        if not title.strip() and not text.strip():
            self._show_notice('请输入便签标题或正文。', error=True)
            return
        try:
            if self._selected_note_id is None:
                note = self._note_repository.add(text, title=title)
            else:
                note = self._note_repository.update(
                    self._selected_note_id, text=text, title=title
                )
        except Exception as exc:
            message = str(exc).strip()
            if not any('\u4e00' <= character <= '\u9fff' for character in message):
                message = '便签保存失败，请检查正文长度。'
            self._show_notice(message, error=True)
            return
        self._selected_note_id = note.note_id
        self._reload_notes(select_note_id=note.note_id)
        self._show_notice('便签已保存在本机。')

    def _delete_note(self) -> None:
        if self._selected_note_id is None:
            self._show_notice('请先选择一条便签。', error=True)
            return
        try:
            deleted = self._note_repository.delete(self._selected_note_id)
        except Exception:
            self._show_notice('便签删除失败。', error=True)
            return
        if not deleted:
            self._show_notice('这条便签已不存在。', error=True)
            return
        self._new_note()
        self._reload_notes()
        self._show_notice('便签已删除。')

    def _on_tab_changed(self, index: int) -> None:
        tool_id = ('timer', 'notes', 'system', 'more')[index]
        if tool_id == 'notes':
            self._reload_notes()
        elif tool_id == 'more':
            self._refresh_recycle_bin()
        self._sync_metrics_sampling()

    def _sync_metrics_sampling(self) -> None:
        should_run = self.isVisible() and self.active_tool == 'system'
        if should_run:
            if not self._metrics_service.active:
                self._metrics_service.start()
            if not self._time_timer.isActive():
                self._time_timer.start()
            self._refresh_clock()
        else:
            self._metrics_service.stop()
            self._time_timer.stop()

    def _on_metrics_updated(self, snapshot: Any) -> None:
        if not snapshot.available:
            self.cpu_label.setText('CPU：不可用')
            self.memory_label.setText('内存：不可用')
            self.metrics_status_label.setText(snapshot.message or '系统指标暂时不可用。')
            return
        cpu = '--' if snapshot.cpu_percent is None else f'{snapshot.cpu_percent:.1f}%'
        memory_percent = (
            '--' if snapshot.memory_percent is None else f'{snapshot.memory_percent:.1f}%'
        )
        self.cpu_label.setText(f'CPU：{cpu}')
        self.memory_label.setText(
            f'内存：{memory_percent} · '
            f'{snapshot.memory_used_mb or 0} / {snapshot.memory_total_mb or 0} MB'
        )
        self.metrics_status_label.setText('系统状态仅在此面板可见时采样。')
        try:
            value = snapshot.captured_at.astimezone().strftime('%H:%M:%S')
        except (AttributeError, ValueError):
            return
        self.system_time_label.setText(f'当前时间：{value}')

    def _refresh_clock(self) -> None:
        from PySide6.QtCore import QDateTime

        self.system_time_label.setText(
            f'当前时间：{QDateTime.currentDateTime().toString("HH:mm:ss")}'
        )

    def _refresh_recycle_bin(self) -> Any:
        try:
            info = self._recycle_bin_service.query()
        except Exception:
            self.recycle_summary_label.setText('无法读取回收站状态。')
            self.recycle_empty_button.setEnabled(False)
            return None
        if not info.available:
            self.recycle_summary_label.setText(info.message or '回收站不可用。')
            self.recycle_empty_button.setEnabled(False)
            return info
        self.recycle_summary_label.setText(
            f'{info.item_count} 个项目，共 {_format_bytes(info.size_bytes)}'
        )
        self.recycle_empty_button.setEnabled(info.item_count > 0)
        return info

    def _empty_recycle_bin(self) -> None:
        info = self._refresh_recycle_bin()
        if info is None or not info.available:
            self._show_notice('无法读取回收站状态。', error=True)
            return
        if info.item_count <= 0:
            self._show_notice('回收站已经是空的。')
            return
        self._show_notice(
            f'即将处理 {info.item_count} 个项目（{_format_bytes(info.size_bytes)}），'
            '请在 Windows 确认窗口中选择。'
        )
        try:
            result = self._recycle_bin_service.empty(parent_hwnd=int(self.winId()))
        except Exception:
            self._show_notice('清空回收站失败。', error=True)
            return
        if result.status == 'completed':
            self._show_notice('回收站已清空。')
            self._refresh_recycle_bin()
        elif result.status == 'cancelled':
            self._show_notice(result.message or '已取消清空回收站。')
        else:
            self._show_notice(result.message or '清空回收站失败。', error=True)

    def _show_notice(self, message: str, *, error: bool = False) -> None:
        self.notice_label.setText(message)
        self.notice_label.setProperty('severity', 'error' if error else 'info')
        self.notice_label.style().unpolish(self.notice_label)
        self.notice_label.style().polish(self.notice_label)
        self.notice_label.show()

    def _available_geometry(self) -> QRect:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return QRect(0, 0, self.width(), self.height())
        return screen.availableGeometry()

    def _fit_to_available_geometry(self) -> None:
        geometry = self._available_geometry()
        inset = 16
        usable_width = max(1, geometry.width() - inset * 2)
        usable_height = max(1, geometry.height() - inset * 2)
        minimum_width = min(360, usable_width)
        minimum_height = min(300, usable_height)
        self.setMinimumSize(minimum_width, minimum_height)
        self.resize(
            max(minimum_width, min(self.width(), usable_width)),
            max(minimum_height, min(self.height(), usable_height)),
        )

    def _update_responsive_layout(self) -> None:
        if not hasattr(self, '_notes_layout') or not hasattr(self, 'tabs'):
            return
        page = self.tabs.currentWidget()
        content_width = page.viewport().width() if isinstance(page, QScrollArea) else 0
        if content_width <= 0:
            content_width = max(0, self.width() - 40)
        self._notes_layout.setDirection(
            QBoxLayout.TopToBottom
            if content_width < 480
            else QBoxLayout.LeftToRight
        )
        compact = self.width() < 520 or self.height() < 430
        margin = 12 if compact else 20
        self._root_layout.setContentsMargins(
            margin,
            12 if compact else 18,
            margin,
            12 if compact else 18,
        )
        for scroll in self._page_scrolls:
            content = scroll.widget()
            if content is not None:
                content.updateGeometry()

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._update_responsive_layout()

    def showEvent(self, event: Any) -> None:
        self._fit_to_available_geometry()
        super().showEvent(event)
        self._update_responsive_layout()
        self._sync_metrics_sampling()

    def hideEvent(self, event: Any) -> None:
        self._metrics_service.stop()
        self._time_timer.stop()
        super().hideEvent(event)

    def _set_style(self) -> None:
        app = QApplication.instance()
        snapshot = getattr(app, 'theme_snapshot', None)
        self.apply_theme(snapshot)

    def apply_theme(self, snapshot) -> None:
        resolved = str(getattr(snapshot, 'resolved', 'light'))
        high_contrast = bool(getattr(snapshot, 'high_contrast', False))
        signature = (resolved, high_contrast)
        if signature == getattr(self, '_theme_signature', None):
            return
        self._theme_signature = signature
        if high_contrast:
            self.setStyleSheet('')
            return
        if resolved == 'dark':
            colors = {
                'window': '#151B26', 'text': '#EEF3FB', 'accent': '#8FB2FF',
                'info': '#202B3E', 'info_border': '#40516C',
                'error': '#3B2325', 'error_border': '#8E4A50',
                'error_text': '#FFC3C7', 'card': '#1D2533', 'border': '#35415A',
            }
        else:
            colors = {
                'window': '#F5F7FB', 'text': '#172033', 'accent': '#365FBD',
                'info': '#E9F0FF', 'info_border': '#B8CCFA',
                'error': '#FFF0EF', 'error_border': '#E6AAA5',
                'error_text': '#8D2720', 'card': '#FFFFFF', 'border': '#D9DFEB',
            }
        self.setStyleSheet(
            f'''
            QWidget#quickToolsWindow {{
                background: {colors['window']};
                color: {colors['text']};
            }}
            QLabel#quickToolsTitle {{
                font-size: 20px;
                font-weight: 700;
            }}
            QLabel#timerDisplay {{
                font-size: 36px;
                font-weight: 700;
                color: {colors['accent']};
                padding: 18px;
            }}
            QLabel#quickToolsNotice {{
                background: {colors['info']};
                border: 1px solid {colors['info_border']};
                border-radius: 8px;
                padding: 8px 10px;
            }}
            QLabel#quickToolsNotice[severity="error"] {{
                background: {colors['error']};
                border-color: {colors['error_border']};
                color: {colors['error_text']};
            }}
            QFrame#toolCard {{
                background: {colors['card']};
                border: 1px solid {colors['border']};
                border-radius: 10px;
            }}
            QLabel#cardHeading {{
                font-size: 16px;
                font-weight: 600;
            }}
            QPushButton {{
                min-height: 30px;
                padding: 3px 12px;
            }}
            '''
        )


def _format_duration(seconds: int) -> str:
    value = max(0, int(seconds))
    hours, remainder = divmod(value, 3_600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f'{hours}:{minutes:02d}:{seconds:02d}'
    return f'{minutes}:{seconds:02d}'


def _format_bytes(size_bytes: int) -> str:
    value = max(0, int(size_bytes))
    if value < 1_024:
        return f'{value} B'
    if value < 1_024 * 1_024:
        return f'{value / 1_024:.1f} KB'
    if value < 1_024 * 1_024 * 1_024:
        return f'{value / (1_024 * 1_024):.1f} MB'
    return f'{value / (1_024 * 1_024 * 1_024):.1f} GB'
