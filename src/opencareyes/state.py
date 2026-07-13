"""Immutable application state shared by every UI surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass(frozen=True, slots=True)
class DisplayState:
    filter_enabled: bool = False
    color_temperature: int = 6500
    dimmer_enabled: bool = False
    dim_level: int = 0
    preset: str = "custom"


@dataclass(frozen=True, slots=True)
class BreakState:
    enabled: bool = False
    phase: str = "stopped"
    mode: str = "pomodoro"
    work_duration: int = 25 * 60
    break_duration: int = 5 * 60
    remaining: int = 0
    total: int = 0
    paused: bool = False
    force_break: bool = False
    countdown_display: str = "tray"


@dataclass(frozen=True, slots=True)
class FocusState:
    enabled: bool = False
    dim_level: int = 150
    session_ends_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AppRuleState:
    app_id: str
    breaks: bool = True
    focus: bool = True
    filter: bool = False
    dimmer: bool = False


@dataclass(frozen=True, slots=True)
class SmartPausePreferencesState:
    enabled: bool = True
    fullscreen_enabled: bool = True
    natural_rest_enabled: bool = True
    app_rules: tuple[AppRuleState, ...] = ()


@dataclass(frozen=True, slots=True)
class AutomationState:
    enabled: bool = False
    mode: str = "sun"
    next_event: str | None = None
    next_event_at: datetime | None = None
    manual_override: bool = False
    on_time: str = "19:00"
    off_time: str = "07:30"
    days: tuple[int, ...] = (0, 1, 2, 3, 4)
    smart_pause: SmartPausePreferencesState = field(
        default_factory=SmartPausePreferencesState
    )


@dataclass(frozen=True, slots=True)
class GlobalPauseState:
    active: bool = False
    mode: str = "none"
    until: datetime | None = None


@dataclass(frozen=True, slots=True)
class CapabilitiesState:
    filter_available: bool = True
    dimmer_available: bool = True
    breaks_available: bool = True
    focus_available: bool = True
    automation_available: bool = True
    hotkeys_available: bool = False


@dataclass(frozen=True, slots=True)
class HotkeyState:
    filter: str = "ctrl+alt+n"
    breaks: str = "ctrl+alt+b"
    dimmer: str = "ctrl+alt+d"
    focus: str = "ctrl+alt+f"


@dataclass(frozen=True, slots=True)
class GeneralState:
    theme: str = "system"
    autostart: bool = False
    onboarding_completed: bool = False
    location_configured: bool = False
    city: str = ""
    latitude: float | None = None
    longitude: float | None = None
    motion_mode: Literal["system", "standard", "reduced"] = "system"
    hotkeys: HotkeyState = field(default_factory=HotkeyState)

    @property
    def first_run_complete(self) -> bool:
        """Compatibility spelling used by early v0.2 UI prototypes."""
        return self.onboarding_completed


@dataclass(frozen=True, slots=True)
class ContextState:
    session: Literal["active", "locked", "suspended"] = "active"
    foreground_app_id: str = ""
    fullscreen: bool = False
    notification_mode: Literal[
        "normal",
        "busy",
        "presentation",
        "d3d_fullscreen",
        "unavailable",
    ] = "normal"
    idle_seconds: int = 0
    captured_at: datetime | None = None
    recent_app_id: str = ""


@dataclass(frozen=True, slots=True)
class FeatureRuntimeState:
    desired_enabled: bool = False
    effective_enabled: bool = False
    suppressed_by: tuple[str, ...] = ()
    resume_condition: str = ""


@dataclass(frozen=True, slots=True)
class EffectivePolicyState:
    filter: FeatureRuntimeState = field(default_factory=FeatureRuntimeState)
    dimmer: FeatureRuntimeState = field(default_factory=FeatureRuntimeState)
    breaks: FeatureRuntimeState = field(default_factory=FeatureRuntimeState)
    focus: FeatureRuntimeState = field(default_factory=FeatureRuntimeState)


@dataclass(frozen=True, slots=True)
class AppState:
    display: DisplayState = field(default_factory=DisplayState)
    breaks: BreakState = field(default_factory=BreakState)
    focus: FocusState = field(default_factory=FocusState)
    automation: AutomationState = field(default_factory=AutomationState)
    global_pause: GlobalPauseState = field(default_factory=GlobalPauseState)
    capabilities: CapabilitiesState = field(default_factory=CapabilitiesState)
    general: GeneralState = field(default_factory=GeneralState)
    context: ContextState = field(default_factory=ContextState)
    effective_policy: EffectivePolicyState = field(default_factory=EffectivePolicyState)
