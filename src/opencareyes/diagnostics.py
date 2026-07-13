"""Privacy-conscious local logging and diagnostic export helpers."""

from __future__ import annotations

import json
import logging
import ntpath
import os
import platform
import re
import sys
import zipfile
from dataclasses import asdict, is_dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

from opencareyes.constants import APP_NAME, APP_VERSION


_QUOTED_WINDOWS_PATH = re.compile(
    r'''(?P<quote>["'])(?:[A-Za-z]:[\\/]|\\\\)[^"'\r\n]*(?P=quote)'''
)
_UNQUOTED_WINDOWS_PATH = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z]:[\\/]|\\\\)[^\r\n]*"
)


def _redact_local_paths(text: str) -> str:
    """Hide quoted drive/UNC paths without removing useful basenames."""

    redacted = _QUOTED_WINDOWS_PATH.sub(
        lambda match: f"{match.group('quote')}<local-path>{match.group('quote')}",
        text,
    )
    # Unquoted native error messages do not provide a reliable path boundary,
    # especially when folder names contain spaces. Redact the remaining line
    # after a drive or UNC prefix rather than risk leaking a complete path.
    return _UNQUOTED_WINDOWS_PATH.sub("<local-path>", redacted)


class _PrivacyFormatter(logging.Formatter):
    """Redact paths after exception and traceback formatting is complete."""

    def format(self, record: logging.LogRecord) -> str:
        return _redact_local_paths(super().format(record))


def log_directory() -> Path:
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    base = Path(root) if root else Path.home() / ".opencareyes"
    return base / APP_NAME / "logs"


def configure_logging() -> Path:
    """Configure a bounded local log without recording user activity."""
    directory = log_directory()
    path = directory / "opencareyes.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(getattr(handler, "_opencareyes_file", False) for handler in root.handlers):
        try:
            directory.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                path,
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
        except OSError as exc:
            # Diagnostics must never prevent the protection features from
            # starting (for example when the directory is read-only or a
            # stale process temporarily owns the file on Windows).
            logging.getLogger(__name__).warning(
                "Local log is unavailable; continuing without file logging: %s",
                exc,
            )
            return path
        handler._opencareyes_file = True  # type: ignore[attr-defined]
        handler.setFormatter(
            _PrivacyFormatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
        )
        root.addHandler(handler)
    return path


def _scrub(value):
    """Remove location-like fields before serialising state."""
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized_key = key.lower()
            if normalized_key in {
                "latitude",
                "longitude",
                "location",
                "city",
                "window_title",
            }:
                continue
            if normalized_key in {"app_id", "foreground_app_id", "recent_app_id"}:
                item = ntpath.basename(item) if isinstance(item, str) else ""
            result[key] = _scrub(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def export_diagnostics(destination: str | os.PathLike, state=None) -> Path:
    """Create a diagnostic ZIP containing metadata, state and bounded logs."""
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "application": APP_NAME,
        "version": APP_VERSION,
        "python": sys.version,
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "state": _scrub(state),
        "privacy": "No window titles, application history, city or coordinates are included.",
    }
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        serialized_payload = json.dumps(payload, ensure_ascii=False, indent=2)
        archive.writestr(
            "diagnostics.json",
            _redact_local_paths(serialized_payload),
        )
        directory = log_directory()
        if directory.exists():
            for path in directory.glob("opencareyes.log*"):
                log_text = path.read_text(encoding="utf-8", errors="replace")
                archive.writestr(
                    f"logs/{path.name}",
                    _redact_local_paths(log_text),
                )
    return output
