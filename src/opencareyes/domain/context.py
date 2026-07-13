"""Immutable context and auto-pause domain values."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

SessionState = Literal["active", "locked", "suspended"]
NotificationMode = Literal[
    "normal",
    "busy",
    "presentation",
    "d3d_fullscreen",
    "unavailable",
]


def _normalise_rule_app_id(value: str) -> str:
    app_id = value.strip().casefold()
    if not app_id:
        raise ValueError("Application identifier cannot be empty")
    if len(app_id) > 128:
        raise ValueError("Application identifier cannot exceed 128 characters")
    if any(character in app_id for character in ("/", "\\", ":", "\0")):
        raise ValueError("Application identifier must be an executable basename")
    if not app_id.endswith(".exe"):
        raise ValueError("Application identifier must end with .exe")
    return app_id


def sanitise_foreground_app_id(value: str) -> str:
    """Return a privacy-safe executable basename, or an empty identifier."""
    app_id = value.strip().casefold()
    if (
        not app_id
        or len(app_id) > 128
        or any(character in app_id for character in ("/", "\\", ":", "\0"))
    ):
        return ""
    return app_id


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    """One privacy-safe observation of the current Windows context."""

    session: SessionState = "active"
    foreground_app_id: str = ""
    fullscreen: bool = False
    notification_mode: NotificationMode = "unavailable"
    idle_seconds: int = 0
    captured_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.session not in {"active", "locked", "suspended"}:
            raise ValueError(f"Unsupported session state: {self.session}")
        if self.notification_mode not in {
            "normal",
            "busy",
            "presentation",
            "d3d_fullscreen",
            "unavailable",
        }:
            raise ValueError(f"Unsupported notification mode: {self.notification_mode}")
        object.__setattr__(
            self,
            "foreground_app_id",
            sanitise_foreground_app_id(self.foreground_app_id),
        )
        object.__setattr__(self, "idle_seconds", max(0, int(self.idle_seconds)))


@dataclass(frozen=True, slots=True)
class AppRule:
    """Per-application suppression choices using basename-only identity."""

    app_id: str
    breaks: bool = True
    focus: bool = True
    filter: bool = False
    dimmer: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "app_id", _normalise_rule_app_id(self.app_id))


@dataclass(frozen=True, slots=True)
class FeatureSuppression:
    """Reasons why one feature is temporarily ineffective."""

    suppressed_by: tuple[str, ...] = ()
    resume_condition: str = ""

    @property
    def suppressed(self) -> bool:
        return bool(self.suppressed_by)


@dataclass(frozen=True, slots=True)
class SuppressionDecision:
    """Pure policy result for all effect-bearing features."""

    filter: FeatureSuppression = field(default_factory=FeatureSuppression)
    dimmer: FeatureSuppression = field(default_factory=FeatureSuppression)
    breaks: FeatureSuppression = field(default_factory=FeatureSuppression)
    focus: FeatureSuppression = field(default_factory=FeatureSuppression)
    natural_rest: bool = False


@dataclass(frozen=True, slots=True)
class AutoPausePreferences:
    """User-owned preferences consumed by the pure auto-pause policy."""

    smart_pause_enabled: bool = True
    fullscreen_pause_enabled: bool = True
    natural_rest_enabled: bool = True
