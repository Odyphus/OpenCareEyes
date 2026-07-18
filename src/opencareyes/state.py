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
    reminder_style: str = "progressive"
    rest_scene: str = 'gaze'


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
    day_profile: str = "office"
    night_profile: str = "night"
    sunrise_offset: int = 0
    sunset_offset: int = 0
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
    settings_read_only: bool = False
    pet_x: int | None = None
    pet_y: int | None = None
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
class DisplayHealthState:
    backend: str = "gamma_ramp"
    status: Literal[
        "ok", "degraded", "suppressed", "error", "unavailable"
    ] = "unavailable"
    hdr_active: bool = False
    pending: bool = False
    transaction_phase: Literal[
        "idle", "applying", "compensating", "completed"
    ] = "idle"
    request_id: int | None = None
    reason_code: str = ""
    message: str = ""


@dataclass(frozen=True, slots=True)
class BreakCadenceState:
    mode: str = "20-20-20"
    short_interval: int = 20 * 60
    short_duration: int = 20
    long_enabled: bool = False
    long_interval: int = 60 * 60
    long_duration: int = 5 * 60
    short_remaining: int = 0
    long_remaining: int = 0


@dataclass(frozen=True, slots=True)
class BreakPromptState:
    kind: str = "none"
    stage: str = "hidden"
    snoozed_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class UserNotice:
    id: str
    severity: Literal["info", "warning", "error"]
    code: str
    message: str
    action: str = ""


@dataclass(frozen=True, slots=True)
class UpdateState:
    status: Literal[
        "idle", "checking", "up_to_date", "available", "failed"
    ] = "idle"
    current_version: str = ""
    latest_version: str = ""
    release_url: str = ""


@dataclass(frozen=True, slots=True)
class PetCatalogEntryState:
    pet_id: str
    display_name: str
    pack_version: str = '1.0.0'
    preview_path: str = ''
    available: bool = True


@dataclass(frozen=True, slots=True)
class PetCatalogState:
    available_pets: tuple[PetCatalogEntryState, ...] = ()
    active_pet_id: str = 'snow_ferret'
    loading_pet_id: str = ''

    @property
    def active_display_name(self) -> str:
        for entry in self.available_pets:
            if entry.pet_id == self.active_pet_id and entry.display_name.strip():
                return entry.display_name.strip()
        return '伙伴'


@dataclass(frozen=True, slots=True)
class PetAppearanceState:
    headwear: str = ''
    neckwear: str = ''
    bodywear: str = ''
    held_item: str = ''
    scene: str = ''
    effect: str = ''


@dataclass(frozen=True, slots=True)
class PetAnchorState:
    edge: Literal[
        'bottom_right', 'bottom_left', 'top_right', 'top_left', 'free'
    ] = 'bottom_right'
    offset: int = 24
    x: int | None = None
    y: int | None = None


@dataclass(frozen=True, slots=True)
class PetState:
    pet_id: str = 'snow_ferret'
    enabled: bool = True
    visible: bool = True
    behavior: str = 'idle'
    mood: str = 'calm'
    scale_percent: int = 100
    appearance: PetAppearanceState = field(default_factory=PetAppearanceState)
    anchor: PetAnchorState = field(default_factory=PetAnchorState)
    bubble: str = 'hidden'
    suppressed_by: tuple[str, ...] = ()
    follow_active_monitor: bool = True
    window_avoidance_enabled: bool = True
    sound_enabled: bool = False


@dataclass(frozen=True, slots=True)
class CompanionPresentationSnapshot:
    """Small, high-frequency companion projection for desktop surfaces.

    Animation and pointer interactions use this snapshot instead of forcing a
    complete :class:`AppState` rebuild. It intentionally contains no business
    settings beyond what the companion surface needs to paint one stable frame.
    """

    pet_id: str = 'snow_ferret'
    action_id: str = 'idle'
    visible: bool = True
    scale_percent: int = 100
    appearance: PetAppearanceState = field(default_factory=PetAppearanceState)
    bubble: str = 'hidden'
    suppressed_by: tuple[str, ...] = ()
    motion_profile: Literal['standard', 'reduced'] = 'standard'


@dataclass(frozen=True, slots=True)
class WeatherState:
    status: Literal['disabled', 'idle', 'loading', 'ready', 'stale', 'failed'] = (
        'disabled'
    )
    condition: str = 'unknown'
    temperature: float | None = None
    observed_at: datetime | None = None
    stale: bool = False
    attribution: str = 'Open-Meteo'
    message: str = ''


@dataclass(frozen=True, slots=True)
class UtilityTimerState:
    status: Literal['idle', 'running', 'paused', 'finished'] = 'idle'
    label: str = ''
    remaining: int = 0
    total: int = 0
    ends_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class QuickToolsState:
    utility_timer: UtilityTimerState = field(default_factory=UtilityTimerState)
    system_panel_visible: bool = False
    hourly_chime_enabled: bool = False
    quiet_hours_start: str = '23:00'
    quiet_hours_end: str = '07:00'
    quick_actions: tuple[str, ...] = ('rest', 'timer', 'notes', 'system')


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
    display_health: DisplayHealthState = field(default_factory=DisplayHealthState)
    break_cadence: BreakCadenceState = field(default_factory=BreakCadenceState)
    break_prompt: BreakPromptState = field(default_factory=BreakPromptState)
    notices: tuple[UserNotice, ...] = ()
    update: UpdateState = field(default_factory=UpdateState)
    pet_catalog: PetCatalogState = field(default_factory=PetCatalogState)
    companion: PetState = field(default_factory=PetState)
    weather: WeatherState = field(default_factory=WeatherState)
    quick_tools: QuickToolsState = field(default_factory=QuickToolsState)
