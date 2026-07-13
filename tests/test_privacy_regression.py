"""Privacy regression tests for state, settings, logs, and diagnostics."""

from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import asdict
from types import SimpleNamespace

import pytest

import opencareyes.app as app_module
import opencareyes.diagnostics as diagnostics
from opencareyes.config.settings import PreferencesRepository
from opencareyes.domain.context import ContextSnapshot
from opencareyes.state import AppState, ContextState


WINDOW_TITLE = "Confidential Q4 Forecast - Board Review"
FULL_EXE_PATH = r"C:\Users\Alice\Private\PrivateApp.exe"
SECOND_EXE_PATH = r"D:\Projects\Secret\PowerPnt.exe"
PERMISSION_PATH = r"D:\Private\OpenCareEyes\locked.log"
TRACEBACK_PATH = r"C:\Users\Alice\Private\secret_module.py"
UNC_PATH = r"\\fileserver\Alice\Secret\report.txt"


def _normalise_serialised_text(text: str) -> str:
    """Undo common JSON/INI escaping before checking privacy sentinels."""

    previous = None
    while text != previous:
        previous = text
        text = text.replace("\\\\", "\\")
    return text.casefold()


def _assert_privacy_safe(text: str) -> None:
    normalised = _normalise_serialised_text(text)
    assert WINDOW_TITLE.casefold() not in normalised
    assert FULL_EXE_PATH.casefold() not in normalised
    assert SECOND_EXE_PATH.casefold() not in normalised


def _close_opencareyes_log_handlers() -> None:
    root = logging.getLogger()
    for handler in tuple(root.handlers):
        if getattr(handler, "_opencareyes_file", False):
            root.removeHandler(handler)
            handler.close()


def _state_from_native_context(app_id: str) -> AppState:
    snapshot = ContextSnapshot(
        foreground_app_id=app_id,
        notification_mode="normal",
    )
    return AppState(
        context=ContextState(
            session=snapshot.session,
            foreground_app_id=snapshot.foreground_app_id,
            fullscreen=snapshot.fullscreen,
            notification_mode=snapshot.notification_mode,
            idle_seconds=snapshot.idle_seconds,
            captured_at=snapshot.captured_at,
        )
    )


def test_app_state_from_native_context_never_contains_full_executable_path():
    state = _state_from_native_context(FULL_EXE_PATH)

    text = json.dumps(asdict(state), ensure_ascii=False, default=str)

    _assert_privacy_safe(text)
    assert state.context.foreground_app_id == ""


def test_configuration_snapshot_and_ini_reject_full_executable_path(
    monkeypatch,
    tmp_path,
):
    settings_path = tmp_path / "opencareeyes.ini"
    monkeypatch.setenv("OPENCAREYES_SETTINGS_PATH", str(settings_path))
    settings = PreferencesRepository()
    unsafe_rule = {
        "app_id": FULL_EXE_PATH,
        "breaks": True,
        "focus": True,
        "filter": False,
        "dimmer": False,
    }

    with pytest.raises(ValueError):
        settings.upsert_app_rule(unsafe_rule)

    settings.upsert_app_rule({**unsafe_rule, "app_id": "privateapp.exe"})
    settings.sync_checked()
    backup_text = json.dumps(settings.snapshot(), ensure_ascii=False, default=str)
    persisted_text = settings_path.read_text(encoding="utf-8")

    _assert_privacy_safe(backup_text)
    _assert_privacy_safe(persisted_text)
    assert "privateapp.exe" in backup_text.casefold()


def test_local_log_of_runtime_state_contains_no_title_or_full_executable_path(
    monkeypatch,
    tmp_path,
):
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(diagnostics, "log_directory", lambda: log_dir)
    close_log_handlers = _close_opencareyes_log_handlers
    close_log_handlers()
    try:
        log_path = diagnostics.configure_logging()
        state = _state_from_native_context(FULL_EXE_PATH)
        logging.getLogger("opencareyes.privacy_test").info(
            "Runtime context: %s",
            state.context,
        )
        for handler in logging.getLogger().handlers:
            if getattr(handler, "_opencareyes_file", False):
                handler.flush()

        _assert_privacy_safe(log_path.read_text(encoding="utf-8"))
    finally:
        close_log_handlers()


def test_log_formatter_and_diagnostic_zip_redact_paths_in_exceptions(
    monkeypatch,
    tmp_path,
):
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(diagnostics, "log_directory", lambda: log_dir)
    _close_opencareyes_log_handlers()
    try:
        log_path = diagnostics.configure_logging()
        source = (
            "raise PermissionError(13, 'access denied', "
            f"{PERMISSION_PATH!r})"
        )
        try:
            exec(compile(source, TRACEBACK_PATH, "exec"))
        except PermissionError:
            logging.getLogger("opencareyes.privacy_test").exception(
                "Cannot read %r",
                UNC_PATH,
            )
        logging.getLogger("opencareyes.privacy_test").error(
            "Unquoted local failure at %s",
            PERMISSION_PATH,
        )
        logging.getLogger("opencareyes.privacy_test").error(
            "Unquoted network failure at %s",
            UNC_PATH,
        )
        logging.getLogger("opencareyes.privacy_test").info(
            "Current application: powerpnt.exe"
        )
        for handler in logging.getLogger().handlers:
            if getattr(handler, "_opencareyes_file", False):
                handler.flush()

        log_text = log_path.read_text(encoding="utf-8")
        assert PERMISSION_PATH.casefold() not in _normalise_serialised_text(log_text)
        assert TRACEBACK_PATH.casefold() not in _normalise_serialised_text(log_text)
        assert UNC_PATH.casefold() not in _normalise_serialised_text(log_text)
        assert 'File "<local-path>"' in log_text
        assert "powerpnt.exe" in log_text.casefold()

        (log_dir / "opencareyes.log.1").write_text(
            f'Legacy failure at "{TRACEBACK_PATH}"\n'
            f"Legacy unquoted failure at {PERMISSION_PATH}\n"
            f"Legacy unquoted network failure at {UNC_PATH}\n",
            encoding="utf-8",
        )
        target = tmp_path / "diagnostics.zip"
        diagnostics.export_diagnostics(target)
        with zipfile.ZipFile(target) as archive:
            zipped_text = "\n".join(
                archive.read(name).decode("utf-8", errors="replace")
                for name in archive.namelist()
            )
        assert PERMISSION_PATH.casefold() not in _normalise_serialised_text(
            zipped_text
        )
        assert TRACEBACK_PATH.casefold() not in _normalise_serialised_text(
            zipped_text
        )
        assert UNC_PATH.casefold() not in _normalise_serialised_text(zipped_text)
        assert "powerpnt.exe" in zipped_text.casefold()
    finally:
        _close_opencareyes_log_handlers()


def test_missing_theme_log_contains_resource_name_but_not_full_path(
    monkeypatch,
    caplog,
):
    private_styles = r"C:\Users\Alice\Private\OpenCareEyes\styles"
    monkeypatch.setattr(app_module, "STYLES_DIR", private_styles)
    fake_app = SimpleNamespace(
        _theme="",
        _resolved_theme="",
        _high_contrast_enabled=False,
        _applied_high_contrast=None,
        _resolve_theme=lambda theme: theme,
        setStyleSheet=lambda _value: None,
        setProperty=lambda _name, _value: None,
        theme_changed=SimpleNamespace(emit=lambda _value: None),
    )

    with caplog.at_level(logging.WARNING, logger=app_module.__name__):
        app_module.OpenCareEyesApp.apply_theme(fake_app, "dark")

    assert private_styles.casefold() not in caplog.text.casefold()
    assert "dark.qss" in caplog.text
    assert "theme=dark" in caplog.text


def test_diagnostic_zip_scrubs_all_state_and_scans_every_member(
    monkeypatch,
    tmp_path,
):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "opencareeyes.log").write_text(
        "OpenCareEyes privacy-safe diagnostic log\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(diagnostics, "log_directory", lambda: log_dir)
    target = tmp_path / "diagnostics.zip"
    unsafe_state = {
        "context": {
            "window_title": WINDOW_TITLE,
            "foreground_app_id": FULL_EXE_PATH,
            "recent_app_id": SECOND_EXE_PATH,
        },
        "rules": [
            {
                "app_id": FULL_EXE_PATH,
                "breaks": True,
            }
        ],
    }

    diagnostics.export_diagnostics(target, unsafe_state)

    with zipfile.ZipFile(target) as archive:
        member_text = "\n".join(
            [*archive.namelist()]
            + [
                archive.read(name).decode("utf-8", errors="replace")
                for name in archive.namelist()
            ]
        )
        payload = json.loads(archive.read("diagnostics.json"))

    _assert_privacy_safe(member_text)
    assert "window_title" not in json.dumps(payload, ensure_ascii=False)
    assert "privateapp.exe" in member_text.casefold()
    assert "powerpnt.exe" in member_text.casefold()
