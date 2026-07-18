from pathlib import Path

from PySide6.QtWidgets import QApplication

from opencareyes.application.companion_coordinator import CompanionCoordinator
from opencareyes.application.pet_asset_repository import PetAssetRepository
from opencareyes.application.pet_pack_registry import PetPackRegistry
from opencareyes.config.settings import Settings
from opencareyes.controller import AppController
from opencareyes.ui.companion_pages import CompanionHomePage, PetCatalogPage


FIXTURE_ROOT = Path(__file__).parent / 'fixtures' / 'pets'


class MemoryStore:
    def __init__(self):
        self.values = {}

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        return type(value) if type is not None and value is not None else value

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


class CountingRegistry(PetPackRegistry):
    def __init__(self, root):
        super().__init__(root, app_version='0.7.0')
        self.available_calls = 0

    def available_pets(self):
        self.available_calls += 1
        return super().available_pets()


def test_sibling_packs_are_validated_only_when_catalog_first_opens(qtbot):
    QApplication.instance() or QApplication([])
    registry = CountingRegistry(FIXTURE_ROOT)
    companion = CompanionCoordinator(registry, 'snow_ferret')
    repository = PetAssetRepository(registry)
    controller = AppController(
        Settings(MemoryStore()),
        companion=companion,
        pet_asset_repository=repository,
    )

    assert registry.available_calls == 0
    assert len(controller.state.pet_catalog.available_pets) == 1
    initial_preview = controller.state.pet_catalog.available_pets[0].preview_path
    assert initial_preview and not Path(initial_preview).is_absolute()

    home = CompanionHomePage(controller, asset_repository=repository)
    qtbot.addWidget(home)
    assert registry.available_calls == 0

    catalog = PetCatalogPage(controller, asset_repository=repository)
    qtbot.addWidget(catalog)
    qtbot.waitUntil(
        lambda: registry.available_calls == 1
        and controller.state.pet_catalog.loading_pet_id == ''
        and len(controller.state.pet_catalog.available_pets) >= 2,
        timeout=5000,
    )

    second_catalog = PetCatalogPage(controller, asset_repository=repository)
    qtbot.addWidget(second_catalog)
    assert registry.available_calls == 1
    assert controller.ensure_pet_catalog_loaded() is False
    assert repository.shutdown()
