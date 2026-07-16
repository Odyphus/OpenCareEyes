"""Project preferences and runtime services into the immutable UI snapshot."""

from __future__ import annotations

from datetime import datetime

from opencareyes.state import (
    AppRuleState,
    AppState,
    AutomationState,
    BreakCadenceState,
    BreakPromptState,
    BreakState,
    CapabilitiesState,
    ContextState,
    DisplayState,
    DisplayHealthState,
    EffectivePolicyState,
    FeatureRuntimeState,
    FocusState,
    GeneralState,
    GlobalPauseState,
    HotkeyState,
    PetAnchorState,
    PetAppearanceState,
    PetCatalogEntryState,
    PetCatalogState,
    PetState,
    QuickToolsState,
    SmartPausePreferencesState,
    UpdateState,
    WeatherState,
)


def _rule_value(rule, key: str, default=False):
    if isinstance(rule, dict):
        return rule.get(key, default)
    return getattr(rule, key, default)


class StateProjector:
    """Build :class:`AppState` without owning timers or mutating services."""

    def __init__(
        self,
        settings,
        *,
        blue_filter=None,
        dimmer=None,
        break_reminder=None,
        focus_mode=None,
        scheduler=None,
        hotkeys=None,
    ):
        self._settings = settings
        self._blue_filter = blue_filter
        self._dimmer = dimmer
        self._break_reminder = break_reminder
        self._focus_mode = focus_mode
        self._scheduler = scheduler
        self._hotkeys = hotkeys

    def build(
        self,
        *,
        focus_session_ends_at: datetime | None = None,
        context: ContextState | None = None,
        effective_policy: EffectivePolicyState | None = None,
        update: UpdateState | None = None,
        display_override: DisplayState | None = None,
        global_pause_override: GlobalPauseState | None = None,
        pet_catalog: PetCatalogState | None = None,
        companion: PetState | None = None,
        weather: WeatherState | None = None,
        quick_tools: QuickToolsState | None = None,
    ) -> AppState:
        settings = self._settings
        reminder = self._break_reminder
        scheduler = self._scheduler
        pause_active = (
            global_pause_override.active
            if global_pause_override is not None
            else self._is_globally_paused()
        )
        until = settings.global_pause_until
        until_datetime = (
            datetime.fromtimestamp(until).astimezone() if until is not None else None
        )
        rules = tuple(
            AppRuleState(
                app_id=str(_rule_value(rule, "app_id", "")),
                breaks=bool(_rule_value(rule, "breaks", True)),
                focus=bool(_rule_value(rule, "focus", True)),
                filter=bool(_rule_value(rule, "filter", False)),
                dimmer=bool(_rule_value(rule, "dimmer", False)),
            )
            for rule in getattr(settings, "app_rules", ())
            if str(_rule_value(rule, "app_id", ""))
        )
        if effective_policy is None:
            effective_policy = self._default_effective_policy()

        return AppState(
            display=(
                display_override
                if display_override is not None
                else DisplayState(
                    filter_enabled=settings.filter_enabled,
                    color_temperature=settings.color_temperature,
                    dimmer_enabled=settings.dimmer_enabled,
                    dim_level=settings.dim_level,
                    preset=settings.current_preset,
                )
            ),
            breaks=BreakState(
                enabled=settings.break_enabled,
                phase=getattr(reminder, "phase", "stopped"),
                mode=settings.break_mode,
                work_duration=settings.work_duration,
                break_duration=settings.break_duration,
                remaining=getattr(reminder, "remaining", 0),
                total=getattr(reminder, "total", 0),
                paused=getattr(reminder, "paused", False),
                force_break=settings.force_break,
                countdown_display=settings.break_countdown_display,
                reminder_style=str(
                    getattr(settings, "break_reminder_style", "progressive")
                ),
                rest_scene=str(getattr(settings, 'break_rest_scene', 'gaze')),
            ),
            focus=FocusState(
                enabled=settings.focus_enabled,
                dim_level=settings.focus_dim_level,
                session_ends_at=focus_session_ends_at,
            ),
            automation=AutomationState(
                enabled=settings.filter_schedule_enabled,
                mode=settings.schedule_mode,
                next_event=getattr(scheduler, "next_event", None),
                next_event_at=getattr(scheduler, "next_event_at", None),
                manual_override=getattr(scheduler, "manual_override", False),
                on_time=settings.schedule_on_time,
                off_time=settings.schedule_off_time,
                days=settings.schedule_days,
                day_profile=str(
                    getattr(settings, "schedule_day_profile", "office")
                ),
                night_profile=str(
                    getattr(settings, "schedule_night_profile", "night")
                ),
                sunrise_offset=int(getattr(settings, "sunrise_offset", 0)),
                sunset_offset=int(getattr(settings, "sunset_offset", 0)),
                smart_pause=SmartPausePreferencesState(
                    enabled=bool(getattr(settings, "smart_pause_enabled", True)),
                    fullscreen_enabled=bool(
                        getattr(settings, "fullscreen_pause_enabled", True)
                    ),
                    natural_rest_enabled=bool(
                        getattr(settings, "natural_rest_enabled", True)
                    ),
                    app_rules=rules,
                ),
            ),
            global_pause=(
                global_pause_override
                if global_pause_override is not None
                else GlobalPauseState(
                    active=pause_active,
                    mode=(
                        settings.global_pause_mode
                        if pause_active
                        else "none"
                    ),
                    until=until_datetime if pause_active else None,
                )
            ),
            capabilities=CapabilitiesState(
                filter_available=self._blue_filter is not None,
                dimmer_available=self._dimmer is not None,
                breaks_available=self._break_reminder is not None,
                focus_available=self._focus_mode is not None,
                automation_available=self._scheduler is not None,
                hotkeys_available=(
                    self._hotkeys is not None
                    and bool(getattr(self._hotkeys, "available", False))
                ),
            ),
            general=GeneralState(
                theme=settings.theme,
                autostart=settings.autostart,
                onboarding_completed=settings.onboarding_completed,
                location_configured=settings.location_configured,
                city=settings.city,
                latitude=settings.latitude if settings.location_configured else None,
                longitude=(
                    settings.longitude if settings.location_configured else None
                ),
                motion_mode=str(getattr(settings, "motion_mode", "system")),
                settings_read_only=bool(
                    getattr(settings, "read_only", False)
                ),
                pet_x=getattr(settings, "pet_x", None),
                pet_y=getattr(settings, "pet_y", None),
                hotkeys=HotkeyState(
                    filter=settings.hotkey_filter,
                    breaks=settings.hotkey_break,
                    dimmer=settings.hotkey_dimmer,
                    focus=settings.hotkey_focus,
                ),
            ),
            context=context or ContextState(),
            effective_policy=effective_policy,
            display_health=self._display_health(),
            break_cadence=BreakCadenceState(
                mode=str(getattr(settings, "cadence_mode", settings.break_mode)),
                short_interval=int(
                    getattr(settings, "cadence_short_interval", settings.work_duration)
                ),
                short_duration=int(
                    getattr(settings, "cadence_short_duration", settings.break_duration)
                ),
                long_enabled=bool(
                    getattr(settings, "cadence_long_enabled", False)
                ),
                long_interval=int(
                    getattr(settings, "cadence_long_interval", 60 * 60)
                ),
                long_duration=int(
                    getattr(settings, "cadence_long_duration", 5 * 60)
                ),
                short_remaining=int(
                    getattr(reminder, "short_remaining", getattr(reminder, "remaining", 0))
                ),
                long_remaining=int(getattr(reminder, "long_remaining", 0)),
            ),
            break_prompt=BreakPromptState(
                kind=str(
                    getattr(
                        reminder,
                        "current_break_kind",
                        getattr(reminder, "due_kind", "none"),
                    )
                    or "none"
                ),
                stage=str(getattr(reminder, "prompt_stage", "none") or "none"),
                snoozed_until=(
                    getattr(reminder, "snoozed_until", None)
                    if isinstance(getattr(reminder, "snoozed_until", None), datetime)
                    else None
                ),
            ),
            update=update or UpdateState(),
            pet_catalog=pet_catalog or self._default_pet_catalog(),
            companion=companion or self._default_companion_state(context),
            weather=weather or WeatherState(
                status=(
                    'idle'
                    if bool(getattr(settings, 'weather_enabled', False))
                    else 'disabled'
                )
            ),
            quick_tools=quick_tools or QuickToolsState(
                hourly_chime_enabled=bool(
                    getattr(settings, 'hourly_chime_enabled', False)
                ),
                quiet_hours_start=str(
                    getattr(settings, 'quiet_hours_start', '23:00')
                ),
                quiet_hours_end=str(
                    getattr(settings, 'quiet_hours_end', '07:00')
                ),
                quick_actions=tuple(
                    getattr(
                        settings,
                        'quick_actions',
                        ('rest', 'timer', 'notes', 'system'),
                    )
                ),
            ),
        )

    def _default_pet_catalog(self) -> PetCatalogState:
        pet_id = str(getattr(self._settings, 'active_pet_id', 'snow_ferret'))
        return PetCatalogState(
            available_pets=(
                PetCatalogEntryState(
                    pet_id='snow_ferret',
                    display_name='鼬鼬',
                ),
            ),
            active_pet_id=pet_id,
        )

    def _default_companion_state(
        self,
        context: ContextState | None,
    ) -> PetState:
        settings = self._settings
        pet_id = str(getattr(settings, 'active_pet_id', 'snow_ferret'))
        preferences = getattr(settings, 'pet_preferences', {})
        slots = preferences.get(pet_id, {}) if isinstance(preferences, dict) else {}
        appearance = PetAppearanceState(
            headwear=str(slots.get('headwear', '')),
            neckwear=str(slots.get('neckwear', '')),
            bodywear=str(slots.get('bodywear', '')),
            held_item=str(slots.get('held_item', '')),
            scene=str(slots.get('scene', '')),
            effect=str(slots.get('effect', '')),
        )
        active_context = context or ContextState()
        suppressed: list[str] = []
        if active_context.session in {'locked', 'suspended'}:
            suppressed.append(active_context.session)
        if active_context.fullscreen:
            suppressed.append('fullscreen')
        enabled = bool(getattr(settings, 'companion_enabled', True))
        return PetState(
            pet_id=pet_id,
            enabled=enabled,
            visible=enabled and not suppressed,
            appearance=appearance,
            scale_percent=int(getattr(settings, 'pet_scale_percent', 100)),
            anchor=PetAnchorState(
                edge=str(getattr(settings, 'pet_anchor_edge', 'bottom_right')),
                offset=int(getattr(settings, 'pet_anchor_offset', 24)),
                x=getattr(settings, 'pet_x', None),
                y=getattr(settings, 'pet_y', None),
            ),
            suppressed_by=tuple(suppressed),
            follow_active_monitor=bool(
                getattr(settings, 'follow_active_monitor', True)
            ),
            window_avoidance_enabled=bool(
                getattr(settings, 'window_avoidance_enabled', True)
            ),
            sound_enabled=bool(
                getattr(settings, 'companion_sound_enabled', False)
            ),
        )

    def _display_health(self) -> DisplayHealthState:
        service = self._blue_filter
        if service is None:
            return DisplayHealthState(
                status="unavailable",
                reason_code="service_unavailable",
                message="色温服务不可用",
            )
        hdr_active = bool(getattr(service, "hdr_active", False))
        pending = bool(
            getattr(
                service,
                "commit_pending",
                getattr(service, "pending", False),
            )
        )
        verified = bool(getattr(service, "capability_verified", False))
        error_code = str(getattr(service, "last_error_code", "") or "")
        if hdr_active:
            return DisplayHealthState(
                status="suppressed",
                hdr_active=True,
                pending=pending,
                reason_code="hdr_active",
                message="HDR 已开启，色温效果已安全暂停",
            )
        if error_code and error_code != "hdr_active":
            return DisplayHealthState(
                status="error",
                pending=pending,
                reason_code=error_code,
                message="色温效果未能安全应用，请重试或恢复原始显示。",
            )
        if not verified:
            return DisplayHealthState(
                status="degraded",
                pending=pending,
                reason_code="capability_probe_unavailable",
                message="显示能力未完全验证，正在使用兼容模式",
            )
        return DisplayHealthState(
            status="ok",
            pending=pending,
            reason_code="sdr_ready",
            message="显示效果可用",
        )

    def _default_effective_policy(self) -> EffectivePolicyState:
        settings = self._settings

        def feature(desired: bool, service) -> FeatureRuntimeState:
            actual = getattr(service, "enabled", desired) if service is not None else False
            return FeatureRuntimeState(
                desired_enabled=desired,
                effective_enabled=bool(actual),
            )

        reminder = self._break_reminder
        break_effective = bool(
            reminder is not None
            and getattr(reminder, "enabled", False)
            and not getattr(reminder, "paused", False)
        )
        return EffectivePolicyState(
            filter=feature(settings.filter_enabled, self._blue_filter),
            dimmer=feature(settings.dimmer_enabled, self._dimmer),
            breaks=FeatureRuntimeState(
                desired_enabled=settings.break_enabled,
                effective_enabled=break_effective,
            ),
            focus=feature(settings.focus_enabled, self._focus_mode),
        )

    def _is_globally_paused(self) -> bool:
        mode = self._settings.global_pause_mode
        if mode != "timed":
            return mode in {"manual", "next_schedule"}
        until = self._settings.global_pause_until
        return until is not None and until > datetime.now().timestamp()
