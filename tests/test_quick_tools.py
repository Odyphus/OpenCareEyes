from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from PySide6.QtCore import QObject, Signal, Qt

from opencareyes.application.note_repository import NoteRepository
from opencareyes.application.utility_timer import UtilityTimerService
from opencareyes.ui.quick_tools import QuickToolsWindow


@dataclass(frozen=True)
class FakeMetricsSnapshot:
    cpu_percent: float | None = 12.5
    memory_percent: float | None = 48.0
    memory_used_mb: int | None = 3_840
    memory_total_mb: int | None = 8_000
    captured_at: datetime = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    available: bool = True
    message: str = ''


class FakeMetricsService(QObject):
    updated = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.active = False
        self.start_calls = 0
        self.stop_calls = 0

    def start(self):
        self.active = True
        self.start_calls += 1
        snapshot = FakeMetricsSnapshot()
        self.updated.emit(snapshot)
        return snapshot

    def stop(self) -> None:
        self.active = False
        self.stop_calls += 1


@dataclass(frozen=True)
class FakeRecycleInfo:
    item_count: int = 3
    size_bytes: int = 2 * 1024 * 1024
    available: bool = True
    message: str = ''


@dataclass(frozen=True)
class FakeRecycleResult:
    status: str = 'completed'
    message: str = ''


class FakeRecycleBinService:
    def __init__(self) -> None:
        self.info = FakeRecycleInfo()
        self.calls: list[object] = []

    def query(self):
        self.calls.append('query')
        return self.info

    def empty(self, *, parent_hwnd: int):
        self.calls.append(('empty', parent_hwnd))
        self.info = FakeRecycleInfo(item_count=0, size_bytes=0)
        return FakeRecycleResult()


def _window(qtbot, tmp_path, clock):
    timer = UtilityTimerService(clock=lambda: clock[0])
    notes = NoteRepository(tmp_path / 'notes.json')
    metrics = FakeMetricsService()
    recycle = FakeRecycleBinService()
    window = QuickToolsWindow(
        timer_service=timer,
        note_repository=notes,
        metrics_service=metrics,
        recycle_bin_service=recycle,
    )
    qtbot.addWidget(window)
    return window, timer, notes, metrics, recycle


def test_user_timer_can_start_tick_pause_resume_and_cancel(qtbot, tmp_path):
    clock = [100.0]
    window, timer, _notes, _metrics, _recycle = _window(qtbot, tmp_path, clock)
    window.show_tool('timer')
    window.timer_minutes_input.setValue(0)
    window.timer_seconds_input.setValue(3)

    qtbot.mouseClick(window.timer_start_button, Qt.LeftButton)
    assert timer.state.status == 'running'
    assert window.timer_display.text() == '0:03'

    clock[0] = 101.1
    timer.poll()
    assert window.timer_display.text() == '0:02'

    qtbot.mouseClick(window.timer_pause_button, Qt.LeftButton)
    assert timer.state.status == 'paused'
    assert window.timer_pause_button.text() == '继续'
    qtbot.mouseClick(window.timer_pause_button, Qt.LeftButton)
    assert timer.state.status == 'running'

    qtbot.mouseClick(window.timer_cancel_button, Qt.LeftButton)
    assert timer.state.status == 'idle'
    assert window.timer_display.text() == '0:00'


def test_timer_rejects_zero_duration_with_visible_error(qtbot, tmp_path):
    window, *_ = _window(qtbot, tmp_path, [100.0])
    window.show_tool('timer')
    window.timer_minutes_input.setValue(0)
    window.timer_seconds_input.setValue(0)

    qtbot.mouseClick(window.timer_start_button, Qt.LeftButton)

    assert window.notice_label.isVisible()
    assert '至少为 1 秒' in window.notice_label.text()
    assert window.notice_label.property('severity') == 'error'


def test_notes_are_added_updated_and_deleted_through_repository(qtbot, tmp_path):
    window, _timer, notes, _metrics, _recycle = _window(qtbot, tmp_path, [100.0])
    window.show_tool('notes')
    window.note_title_input.setText('复习计划')
    window.note_text_input.setPlainText('完成第三章习题')

    qtbot.mouseClick(window.note_save_button, Qt.LeftButton)
    stored = notes.list_notes()
    assert len(stored) == 1
    assert stored[0].title == '复习计划'
    assert window.notes_list.count() == 1

    window.note_text_input.setPlainText('完成第三、四章习题')
    qtbot.mouseClick(window.note_save_button, Qt.LeftButton)
    assert notes.list_notes()[0].text == '完成第三、四章习题'

    qtbot.mouseClick(window.note_delete_button, Qt.LeftButton)
    assert notes.list_notes() == ()
    assert window.notes_list.count() == 0


def test_notes_limit_error_is_visible_and_does_not_drop_existing_notes(qtbot, tmp_path):
    window, _timer, notes, _metrics, _recycle = _window(qtbot, tmp_path, [100.0])
    for index in range(50):
        notes.add(f'正文 {index}', title=f'便签 {index}')
    window.show_tool('notes')
    window._new_note()
    window.note_text_input.setPlainText('第 51 条')

    qtbot.mouseClick(window.note_save_button, Qt.LeftButton)

    assert len(notes.list_notes()) == 50
    assert '50 条' in window.notice_label.text()
    assert window.notice_label.property('severity') == 'error'


def test_system_metrics_only_sample_while_system_tab_is_visible(qtbot, tmp_path):
    window, _timer, _notes, metrics, _recycle = _window(qtbot, tmp_path, [100.0])
    window.show_tool('system')

    assert metrics.active
    assert metrics.start_calls == 1
    assert '12.5%' in window.cpu_label.text()
    assert '48.0%' in window.memory_label.text()

    window.show_tool('timer')
    assert not metrics.active
    window.show_tool('status')
    assert metrics.start_calls == 2

    window.hide()
    assert not metrics.active


def test_recycle_bin_summary_precedes_windows_confirming_empty_call(qtbot, tmp_path):
    window, _timer, _notes, _metrics, recycle = _window(qtbot, tmp_path, [100.0])
    window.show_tool('more')
    assert window.recycle_summary_label.text() == '3 个项目，共 2.0 MB'

    recycle.calls.clear()
    qtbot.mouseClick(window.recycle_empty_button, Qt.LeftButton)

    assert recycle.calls[0] == 'query'
    assert recycle.calls[1][0] == 'empty'
    assert isinstance(recycle.calls[1][1], int)
    assert '已清空' in window.notice_label.text()


def test_unknown_tool_is_rejected_without_destroying_window(qtbot, tmp_path):
    window, *_ = _window(qtbot, tmp_path, [100.0])

    with pytest.raises(ValueError, match='unknown quick tool'):
        window.show_tool('calendar')

    assert not window.testAttribute(Qt.WA_DeleteOnClose)
