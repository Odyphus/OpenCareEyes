"""Serial, asynchronous access to the Windows Gamma Ramp backend."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication

from opencareyes.core.blue_light_filter import BlueLightFilter

log = logging.getLogger(__name__)


def _display_failure_message(code: str) -> str:
    """Return a fixed user message for native display failures."""

    if code == "hdr_active":
        return "HDR 已开启，色温调节已暂停；可改用 Windows 夜间模式。"
    if code == "gamma_rollback_failed":
        return "显示效果回滚不完整，请重启 OpenCareEyes 后检查显示。"
    if code in {
        "display_identity_unavailable",
        "gamma_baseline_unavailable",
        "gamma_capture_failed",
        "gamma_verification_failed",
    }:
        return "无法验证当前显示器的原始色彩状态，已停止应用色温效果。"
    return "色温效果未能安全应用，已保持原始显示。"


@dataclass(frozen=True, slots=True)
class _Command:
    token: "GammaRequestToken"


@dataclass(frozen=True, slots=True)
class GammaRequestToken:
    """Identity and purpose of one serialized native Gamma request."""

    request_id: int
    revision: int
    kind: str
    purpose: str
    requested_value: int | None = None


@dataclass(frozen=True, slots=True)
class GammaResult:
    """Verified native result associated with exactly one request token."""

    token: GammaRequestToken
    success: bool
    superseded: bool
    enabled: bool
    temperature: int
    hdr_active: bool
    capability_verified: bool
    code: str = ""
    message: str = ""

    @property
    def request_id(self) -> int:
        return self.token.request_id

    @property
    def revision(self) -> int:
        return self.token.revision

    @property
    def kind(self) -> str:
        return self.token.kind

    @property
    def purpose(self) -> str:
        return self.token.purpose

    @property
    def requested_value(self) -> int | None:
        return self.token.requested_value


class _GammaWorker(QObject):
    completed = Signal(int, bool, object)
    shutdown_completed = Signal()

    def __init__(self, backend: BlueLightFilter):
        super().__init__()
        self._backend = backend

    @Slot(object)
    def execute(self, command: _Command) -> None:
        token = command.token
        try:
            if token.kind == "enable":
                success = self._backend.enable(
                    int(token.requested_value or 6500)
                )
            elif token.kind == "disable":
                success = self._backend.disable()
            elif token.kind == "temperature":
                success = self._backend.set_temperature(
                    int(token.requested_value or 6500)
                )
            elif token.kind == "refresh":
                result = self._backend.refresh_screens()
                success = (
                    bool(result)
                    if result is not None
                    else self._backend.last_error_code in {"", "hdr_active"}
                )
            else:
                success = False
        except Exception:
            log.exception("Gamma worker command failed: %s", token.kind)
            success = False
            payload = self._snapshot()
            payload.update(
                error_code="gamma_worker_exception",
                error_message="色温效果未能安全应用，已保持原始显示。",
            )
        else:
            payload = self._snapshot()
        self.completed.emit(token.request_id, bool(success), payload)

    @Slot()
    def shutdown(self) -> None:
        try:
            self._backend.disable()
        finally:
            self.shutdown_completed.emit()

    def _snapshot(self) -> dict[str, object]:
        return {
            "enabled": bool(getattr(self._backend, "enabled", False)),
            "temperature": int(
                getattr(self._backend, "current_temperature", 6500)
            ),
            "hdr_active": bool(getattr(self._backend, "hdr_active", False)),
            "verified": bool(
                getattr(self._backend, "capability_verified", False)
            ),
            "error_code": str(getattr(self._backend, "last_error_code", "") or ""),
            "error_message": str(
                getattr(self._backend, "last_error_message", "") or ""
            ),
        }


class QueuedBlueLightFilter(QObject):
    """BlueLightFilter-compatible facade whose native work is serialized.

    Calls report acceptance. ``enabled`` is the last verified result and
    ``pending`` remains true until the native operation has completed.
    """

    _execute_requested = Signal(object)
    _shutdown_requested = Signal()
    state_changed = Signal()
    operation_finished = Signal(bool, str, str)
    operation_failed = Signal(str, str)
    request_finished = Signal(object)

    def __init__(
        self,
        backend: BlueLightFilter | None = None,
        parent: QObject | None = None,
        *,
        auto_watch_screens: bool = True,
    ) -> None:
        super().__init__(parent)
        self._backend = backend or BlueLightFilter(connect_screen_events=False)
        self._enabled = bool(self._backend.enabled)
        self._temperature = int(self._backend.current_temperature)
        self._hdr_active = bool(self._backend.hdr_active)
        self._verified = bool(self._backend.capability_verified)
        self._error_code = str(self._backend.last_error_code or "")
        self._error_message = str(self._backend.last_error_message or "")
        self._next_identifier = 1
        self._pending: dict[int, GammaRequestToken] = {}
        self._queued_preview: GammaRequestToken | None = None
        self._last_request_token: GammaRequestToken | None = None
        self._latest_result_id = 0
        self._temperature_timer = QTimer(self)
        self._temperature_timer.setSingleShot(True)
        self._temperature_timer.setInterval(50)
        self._temperature_timer.timeout.connect(self._submit_temperature)

        self._thread = QThread(self)
        self._worker = _GammaWorker(self._backend)
        self._worker.moveToThread(self._thread)
        self._execute_requested.connect(self._worker.execute, Qt.QueuedConnection)
        self._shutdown_requested.connect(self._worker.shutdown, Qt.QueuedConnection)
        self._worker.completed.connect(self._complete, Qt.QueuedConnection)
        # shutdown() waits from the GUI thread, so quitting must not be queued
        # back to that blocked thread.
        self._worker.shutdown_completed.connect(
            self._thread.quit,
            Qt.DirectConnection,
        )
        self._thread.start()

        app = QApplication.instance()
        if auto_watch_screens and app is not None:
            app.screenAdded.connect(self.refresh_screens)
            app.screenRemoved.connect(self.refresh_screens)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def current_temperature(self) -> int:
        return self._temperature

    @property
    def pending(self) -> bool:
        return bool(self._pending) or self._temperature_timer.isActive()

    @property
    def pending_target(self) -> bool | None:
        for token in reversed(tuple(self._pending.values())):
            if token.kind == "enable":
                return True
            if token.kind == "disable":
                return False
        return None

    @property
    def commit_pending(self) -> bool:
        return any(
            token.purpose != "preview"
            for token in self._pending.values()
        )

    @property
    def preview_pending(self) -> bool:
        return any(
            token.purpose == "preview"
            for token in self._pending.values()
        )

    @property
    def last_request_id(self) -> int:
        token = self._last_request_token
        return token.request_id if token is not None else 0

    @property
    def last_request_token(self) -> GammaRequestToken | None:
        return self._last_request_token

    @property
    def hdr_active(self) -> bool:
        return self._hdr_active

    @property
    def capability_verified(self) -> bool:
        return self._verified

    @property
    def last_error_code(self) -> str:
        return self._error_code

    @property
    def last_error_message(self) -> str:
        return self._error_message

    def enable(self, temperature: int = 6500) -> bool:
        self.request_enable(int(temperature), purpose="legacy")
        return True

    def disable(self) -> bool:
        self.request_disable(purpose="legacy")
        return True

    def set_temperature(self, temperature: int) -> bool:
        """Compatibility API: coalesce an ephemeral temperature preview."""

        self.preview_temperature(int(temperature))
        return True

    def request_enable(
        self,
        temperature: int = 6500,
        *,
        revision: int = 0,
        purpose: str = "commit",
    ) -> GammaRequestToken:
        token = self._reserve(
            "enable",
            int(temperature),
            revision,
            purpose,
        )
        self._cancel_temperature_preview()
        self._dispatch(token)
        return token

    def request_disable(
        self,
        *,
        revision: int = 0,
        purpose: str = "commit",
    ) -> GammaRequestToken:
        token = self._reserve("disable", None, revision, purpose)
        self._cancel_temperature_preview()
        self._dispatch(token)
        return token

    def request_temperature(
        self,
        temperature: int,
        *,
        revision: int = 0,
        purpose: str = "commit",
    ) -> GammaRequestToken:
        """Submit an immediate, independently verifiable commit barrier."""

        token = self._reserve(
            "temperature",
            int(temperature),
            revision,
            purpose,
        )
        self._cancel_temperature_preview()
        self._dispatch(token)
        return token

    def preview_temperature(
        self,
        temperature: int,
        *,
        revision: int = 0,
    ) -> GammaRequestToken:
        token = self._reserve(
            "temperature",
            int(temperature),
            revision,
            "preview",
        )
        self._cancel_temperature_preview()
        self._queued_preview = token
        self._temperature_timer.start()
        self.state_changed.emit()
        return token

    def refresh_screens(self, *_args) -> bool:
        self.request_refresh()
        return True

    def request_refresh(
        self,
        *,
        revision: int = 0,
        purpose: str = "system",
    ) -> GammaRequestToken:
        token = self._reserve("refresh", None, revision, purpose)
        self._dispatch(token)
        return token

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        self._cancel_temperature_preview()
        if not self._thread.isRunning():
            return True
        self._shutdown_requested.emit()
        return bool(self._thread.wait(max(1, int(timeout_ms))))

    def _submit_temperature(self) -> None:
        token = self._queued_preview
        self._queued_preview = None
        if token is not None and token.request_id in self._pending:
            self._dispatch(token)

    def _cancel_temperature_preview(self) -> None:
        self._temperature_timer.stop()
        token = self._queued_preview
        self._queued_preview = None
        if token is None or token.request_id not in self._pending:
            return
        self._pending.pop(token.request_id, None)
        result = self._result(
            token,
            success=False,
            superseded=True,
            code="preview_superseded",
            message="预览已由更新的显示请求替代。",
        )
        self.request_finished.emit(result)
        self.state_changed.emit()

    def _reserve(
        self,
        kind: str,
        value: int | None,
        revision: int,
        purpose: str,
    ) -> GammaRequestToken:
        token = GammaRequestToken(
            request_id=self._next_identifier,
            revision=max(0, int(revision)),
            kind=str(kind),
            purpose=str(purpose),
            requested_value=value,
        )
        self._next_identifier += 1
        self._pending[token.request_id] = token
        self._last_request_token = token
        return token

    def _dispatch(self, token: GammaRequestToken) -> None:
        self.state_changed.emit()
        self._execute_requested.emit(_Command(token))

    @Slot(int, bool, object)
    def _complete(self, identifier: int, success: bool, payload: object) -> None:
        token = self._pending.pop(int(identifier), None)
        if token is None:
            return
        data = payload if isinstance(payload, dict) else {}
        superseded = token.request_id < self._latest_result_id
        code = str(data.get("error_code", "") or "") or (
            "" if success else "gamma_apply_failed"
        )
        raw_message = str(data.get("error_message", "") or "")
        message = "" if success else _display_failure_message(code)
        if not success and raw_message:
            log.error("Gamma operation failed [%s]: %s", code, raw_message)
        if not superseded:
            self._latest_result_id = token.request_id
            self._enabled = bool(data.get("enabled", False))
            self._temperature = int(data.get("temperature", self._temperature))
            self._hdr_active = bool(data.get("hdr_active", False))
            self._verified = bool(data.get("verified", False))
            self._error_code = code
            self._error_message = message
        result = self._result(
            token,
            success=bool(success),
            superseded=superseded,
            data=data,
            code=code,
            message=message,
        )
        self.state_changed.emit()
        self.request_finished.emit(result)
        self.operation_finished.emit(bool(success), code, message)
        has_newer_pending = any(
            pending.request_id > token.request_id
            for pending in self._pending.values()
        )
        if not success and not superseded and not has_newer_pending:
            self.operation_failed.emit(code, message)

    def _result(
        self,
        token: GammaRequestToken,
        *,
        success: bool,
        superseded: bool,
        data: dict[str, object] | None = None,
        code: str = "",
        message: str = "",
    ) -> GammaResult:
        data = data or {}
        return GammaResult(
            token=token,
            success=bool(success),
            superseded=bool(superseded),
            enabled=bool(data.get("enabled", self._enabled)),
            temperature=int(data.get("temperature", self._temperature)),
            hdr_active=bool(data.get("hdr_active", self._hdr_active)),
            capability_verified=bool(data.get("verified", self._verified)),
            code=str(code),
            message=str(message),
        )
