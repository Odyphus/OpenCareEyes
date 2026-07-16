from types import SimpleNamespace

from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QSignalSpy

from opencareyes.application.pet_asset_repository import PetAssetRepository


class _Registry:
    def __init__(self, path):
        self.path = path
        self.calls = []

    def resolve_resource(self, pet_id, resource_path):
        self.calls.append((pet_id, resource_path))
        return self.path


def _write_image(path, color='#6B9EEA'):
    image = QImage(32, 32, QImage.Format_ARGB32)
    image.fill(QColor(color))
    assert image.save(str(path))


def test_async_decode_returns_fallback_then_publishes_cached_frame(qtbot, tmp_path):
    path = tmp_path / 'atlas.png'
    _write_image(path)
    registry = _Registry(path)
    repository = PetAssetRepository(registry)
    ready = QSignalSpy(repository.resource_ready)

    assert repository.load_frame('snow_ferret', 'sprites/atlas.png') is None
    qtbot.waitUntil(lambda: ready.count() == 1, timeout=2000)
    loaded = repository.load_frame('snow_ferret', 'sprites/atlas.png')

    assert loaded is not None and not loaded.isNull()
    assert registry.calls == [('snow_ferret', 'sprites/atlas.png')]
    assert repository.pending_count == 0
    assert repository.shutdown()


def test_manifest_preload_deduplicates_shared_atlas(qtbot, tmp_path):
    path = tmp_path / 'atlas.png'
    _write_image(path)
    registry = _Registry(path)
    repository = PetAssetRepository(registry)
    ready = QSignalSpy(repository.resource_ready)
    frame = SimpleNamespace(path='sprites/atlas.png')
    manifest = SimpleNamespace(
        pet_id='snow_ferret',
        actions={
            'idle': SimpleNamespace(frames=(frame, frame)),
            'move': SimpleNamespace(frames=(frame,)),
        },
    )

    repository.preload_manifest(manifest)
    qtbot.waitUntil(lambda: ready.count() == 1, timeout=2000)

    assert registry.calls == [('snow_ferret', 'sprites/atlas.png')]
    assert repository.cache_bytes > 0
    assert repository.shutdown()
