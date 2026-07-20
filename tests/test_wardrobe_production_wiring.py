'''Cross-species production wiring tests for the declarative wardrobe.'''

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from opencareyes.application.companion_coordinator import CompanionCoordinator
from opencareyes.application.companion_runtime import CompanionRuntime
from opencareyes.application.pet_asset_repository import PetAssetRepository
from opencareyes.application.pet_pack_registry import PetPackRegistry
from opencareyes.config.settings import Settings
from opencareyes.controller import AppController
from opencareyes.ui.pet_surface import PetSurface


FIXTURE_ROOT = Path(__file__).parent / 'fixtures' / 'pets'


class MemoryStore:
    def __init__(self):
        self.values = {}

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        if type is not None and value is not None:
            return type(value)
        return value

    def setValue(self, key, value):
        self.values[key] = value

    def allKeys(self):
        return list(self.values)

    def sync(self):
        return None

    def clear(self):
        self.values.clear()

    def remove(self, key):
        self.values.pop(key, None)


class FakeBubble(QObject):
    start_due_requested = Signal()
    snooze_requested = Signal(int)
    skip_requested = Signal()
    dismissed = Signal()
    tool_requested = Signal(str)
    item_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.is_rest_prompt_active = False

    def show_rest_prompt(self, _anchor, **_kwargs):
        self.is_rest_prompt_active = True

    def clear_rest_prompt(self):
        self.is_rest_prompt_active = False

    def hide(self):
        return None

    def isVisible(self):
        return False

    def set_status(self, _title, _detail):
        return None

    def set_break_countdown(self, _remaining, _total):
        return None

    def set_quick_actions(self, _actions):
        return None


class FakeApplication(QObject):
    motion_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.motion_enabled = True

    def topLevelWidgets(self):
        return QApplication.topLevelWidgets()

    def screenAt(self, point):
        return QApplication.screenAt(point)

    def primaryScreen(self):
        return QApplication.primaryScreen()

    def set_pet_accent(self, _accent):
        return None


def test_tiny_bird_outfit_commits_once_through_production_wiring(qtbot):
    registry = PetPackRegistry(FIXTURE_ROOT, app_version='0.8.0')
    manifest = registry.load('tiny_bird')
    companion = CompanionCoordinator(registry, 'tiny_bird')
    repository = PetAssetRepository(registry)
    settings = Settings(MemoryStore())
    settings.active_pet_id = 'tiny_bird'
    settings.motion_mode = 'reduced'
    controller = AppController(
        settings,
        companion=companion,
        pet_asset_repository=repository,
    )
    surface = PetSurface(repository)
    bubble = FakeBubble()
    runtime = CompanionRuntime(
        controller,
        companion,
        surface,
        bubble,
        application=FakeApplication(),
        asset_repository=repository,
        pet_registry=registry,
        settings=settings,
    )
    controller.attach_companion_surface(surface)
    runtime.start()
    state_spy = QSignalSpy(controller.state_changed)
    presentation_spy = QSignalSpy(controller.companion_presentation_changed)

    try:
        assert surface.pet_id == 'tiny_bird'
        assert controller.set_pet_outfit('rain_cape') is True

        # Decoding happens on the repository worker; no optimistic semantic
        # state is published before the queued completion reaches the GUI thread.
        assert state_spy.count() == 0
        assert companion.state.outfit_id == ''

        qtbot.waitUntil(
            lambda: surface.outfit_id == 'rain_cape',
            timeout=3000,
        )

        assert settings.wardrobe_mode == 'outfit'
        assert settings.outfit_preferences == {'tiny_bird': 'rain_cape'}
        assert companion.state.pet_id == 'tiny_bird'
        assert companion.state.outfit_id == 'rain_cape'
        assert controller.state.companion.pet_id == 'tiny_bird'
        assert controller.state.companion.outfit_id == 'rain_cape'
        assert controller.state.pet_wardrobe.effective_outfit_id == 'rain_cape'
        assert controller.companion_presentation.pet_id == 'tiny_bird'
        assert controller.companion_presentation.outfit_id == 'rain_cape'
        assert surface.pet_id == 'tiny_bird'
        assert surface.outfit_id == 'rain_cape'
        assert state_spy.count() == 1
        assert presentation_spy.count() == 1

        outfit_idle = manifest.outfits['rain_cape'].actions['idle']
        assert outfit_idle is not manifest.actions['idle']
        assert companion.dispatch_kind('click') is True
        assert companion.current_action is outfit_idle
        assert registry.resolve_action(
            manifest,
            'click',
            outfit_id='rain_cape',
        ) is outfit_idle
        assert surface.has_action('click_reaction') is False
        assert surface._action('click_reaction') is outfit_idle
        assert surface.play_action('click_reaction', restart=True) is True
        assert surface.action_id == 'idle'
        assert surface.pet_id == 'tiny_bird'
        assert surface.outfit_id == 'rain_cape'
    finally:
        runtime.shutdown()
        surface.close()
        repository.shutdown()
