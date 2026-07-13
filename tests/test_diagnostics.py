import json
import logging
import zipfile
from dataclasses import dataclass

import opencareyes.diagnostics as diagnostics
from opencareyes.diagnostics import export_diagnostics
from opencareyes.state import AppState, ContextState


@dataclass(frozen=True)
class _AutomationState:
    enabled: bool = True
    latitude: float = 39.9
    longitude: float = 116.4


def test_diagnostic_export_scrubs_location(tmp_path):
    target = tmp_path / "diagnostics.zip"

    export_diagnostics(target, _AutomationState())

    with zipfile.ZipFile(target) as archive:
        payload = json.loads(archive.read("diagnostics.json"))
    assert payload["state"] == {"enabled": True}
    assert "latitude" not in json.dumps(payload)
    assert "longitude" not in json.dumps(payload)


def test_logging_failure_does_not_block_startup(monkeypatch, tmp_path):
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_opencareeyes_file", False):
            root.removeHandler(handler)
            handler.close()

    monkeypatch.setattr(diagnostics, "log_directory", lambda: tmp_path)

    def fail_to_open(*args, **kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr(diagnostics, "RotatingFileHandler", fail_to_open)

    assert diagnostics.configure_logging().as_posix() == (
        tmp_path / "opencareyes.log"
    ).as_posix()


def test_diagnostic_export_never_contains_window_title_or_executable_path(tmp_path):
    target = tmp_path / "diagnostics.zip"
    state = AppState(context=ContextState(
        foreground_app_id=r"C:\Private\Game.exe",
        recent_app_id=r"D:\Work\PowerPnt.exe",
    ))

    export_diagnostics(target, state)

    with zipfile.ZipFile(target) as archive:
        text = archive.read("diagnostics.json").decode("utf-8")
    assert "C:\\Private" not in text
    assert "D:\\Work" not in text
    assert "game.exe" in text.lower()
    assert "powerpnt.exe" in text.lower()
