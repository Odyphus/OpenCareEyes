"""Run explicit update checks away from the Qt GUI thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot

from opencareyes.application.update_service import ManualUpdateService
from opencareyes.state import UpdateState


class _TaskSignals(QObject):
    finished = Signal(object)


class _UpdateTask(QRunnable):
    def __init__(self, service: ManualUpdateService):
        super().__init__()
        self._service = service
        self.signals = _TaskSignals()

    def run(self) -> None:
        try:
            state = self._service.check_for_updates()
        except Exception:
            # The service already contains a defensive network boundary. Keep
            # this last guard so an injected/test opener cannot strand the UI
            # in the checking state.
            state = UpdateState(
                "failed",
                self._service.state.current_version,
            )
        self.signals.finished.emit(state)


class UpdateChecker(QObject):
    """User-triggered, single-flight update-check coordinator."""

    state_changed = Signal(object)
    operation_failed = Signal(str, str)

    def __init__(
        self,
        service: ManualUpdateService | None = None,
        *,
        thread_pool: QThreadPool | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service or ManualUpdateService()
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._state = self._service.state
        self._task: _UpdateTask | None = None

    @property
    def state(self) -> UpdateState:
        return self._state

    def check(self) -> bool:
        """Accept one explicit request and return immediately."""

        if self._state.status == "checking":
            return False
        self._state = UpdateState(
            "checking",
            self._service.state.current_version,
        )
        self.state_changed.emit(self._state)
        task = _UpdateTask(self._service)
        task.signals.finished.connect(self._finish, Qt.QueuedConnection)
        self._task = task
        self._thread_pool.start(task)
        return True

    @Slot(object)
    def _finish(self, state: UpdateState) -> None:
        self._task = None
        self._state = state
        self.state_changed.emit(state)
        if state.status == "failed":
            self.operation_failed.emit(
                "update_check",
                "检查更新失败，请检查网络连接后重试。",
            )
