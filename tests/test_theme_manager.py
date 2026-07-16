from pathlib import Path

from opencareyes.ui.theme import (
    BRAND_ACCENT,
    DEFAULT_PET_ACCENT,
    WARM_ACCENT,
    ThemeManager,
)


def _manager(system: dict[str, object]) -> ThemeManager:
    return ThemeManager(
        theme_detector=lambda: str(system["theme"]),
        high_contrast_detector=lambda: bool(system["high_contrast"]),
        animation_detector=lambda: bool(system["animations"]),
        battery_saver_detector=lambda: bool(system.get("battery_saver", False)),
    )


def test_theme_snapshot_resolves_user_and_system_preferences() -> None:
    system = {"theme": "light", "high_contrast": False, "animations": True}
    manager = _manager(system)

    assert manager.snapshot.requested == "system"
    assert manager.snapshot.resolved == "light"
    assert manager.snapshot.motion_profile == "standard"
    assert manager.snapshot.brand_accent == BRAND_ACCENT
    assert manager.snapshot.warm_accent == WARM_ACCENT

    snapshot = manager.set_preferences(theme="dark", motion_mode="reduced")

    assert snapshot.requested == "dark"
    assert snapshot.resolved == "dark"
    assert snapshot.motion_profile == "reduced"


def test_theme_manager_publishes_only_semantic_system_changes() -> None:
    system = {"theme": "light", "high_contrast": False, "animations": True}
    manager = _manager(system)
    events = []
    manager.snapshot_changed.connect(events.append)

    manager.refresh_system_preferences()
    assert events == []

    system["theme"] = "dark"
    manager.refresh_system_preferences()
    system["animations"] = False
    manager.refresh_system_preferences()
    system["high_contrast"] = True
    manager.refresh_system_preferences()

    assert [event.resolved for event in events] == ["dark", "dark", "dark"]
    assert events[-2].motion_profile == "reduced"
    assert events[-1].high_contrast is True


def test_explicit_preferences_ignore_unrelated_system_changes() -> None:
    system = {"theme": "light", "high_contrast": False, "animations": False}
    manager = _manager(system)
    manager.set_preferences(theme="dark", motion_mode="standard")
    events = []
    manager.snapshot_changed.connect(events.append)

    system["theme"] = "dark"
    system["animations"] = True
    manager.refresh_system_preferences()

    assert events == []
    assert manager.snapshot.resolved == "dark"
    assert manager.snapshot.motion_profile == "standard"


def test_invalid_preferences_fall_back_without_species_assumptions() -> None:
    system = {"theme": "light", "high_contrast": False, "animations": True}
    manager = _manager(system)

    snapshot = manager.set_preferences(
        theme="unknown",
        motion_mode="fast",
        pet_accent="not-a-colour",
    )

    assert snapshot.requested == "system"
    assert snapshot.motion_profile == "standard"
    assert snapshot.pet_accent == DEFAULT_PET_ACCENT
    assert "ferret" not in repr(snapshot).casefold()

    assert manager.set_preferences(pet_accent="#12abEF").pet_accent == "#12ABEF"


def test_theme_styles_cover_complex_and_accessibility_controls() -> None:
    styles_dir = Path(__file__).parents[1] / "assets" / "styles"
    required = (
        "QTabWidget",
        "QTabBar",
        "QTableWidget",
        "QHeaderView",
        "QTextEdit",
        "QListWidget",
        ':focus',
        ':disabled',
        '[error="true"]',
    )

    for filename in ("light.qss", "dark.qss"):
        stylesheet = (styles_dir / filename).read_text(encoding="utf-8")
        assert all(selector in stylesheet for selector in required)


def test_system_motion_reduces_on_battery_saver_but_explicit_standard_wins() -> None:
    system = {
        "theme": "light",
        "high_contrast": False,
        "animations": True,
        "battery_saver": True,
    }
    manager = _manager(system)

    assert manager.snapshot.motion_profile == "reduced"
    assert manager.set_preferences(motion_mode="standard").motion_profile == "standard"
