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
            'move': SimpleNamespace(frames=(SimpleNamespace(path='sprites/move.png'),)),
        },
    )

    repository.preload_manifest(manifest)
    qtbot.waitUntil(lambda: ready.count() == 1, timeout=2000)

    assert registry.calls == [('snow_ferret', 'sprites/atlas.png')]
    assert repository.cache_bytes > 0
    assert repository.shutdown()


def test_outfit_preload_only_decodes_selected_idle_atlas(qtbot, tmp_path):
    path = tmp_path / 'atlas.png'
    _write_image(path)
    registry = _Registry(path)
    repository = PetAssetRepository(registry)
    ready = QSignalSpy(repository.resource_ready)
    idle_frame = SimpleNamespace(path='outfits/skier/idle_atlas.png')
    move_frame = SimpleNamespace(path='outfits/skier/move_atlas.png')
    other_frame = SimpleNamespace(path='outfits/mage/idle_atlas.png')
    manifest = SimpleNamespace(
        pet_id='snow_ferret',
        outfits={
            'snow_slope_skier': SimpleNamespace(
                actions={
                    'idle': SimpleNamespace(frames=(idle_frame, idle_frame)),
                    'move': SimpleNamespace(frames=(move_frame,)),
                },
            ),
            'thunder_mage': SimpleNamespace(
                actions={'idle': SimpleNamespace(frames=(other_frame,))},
            ),
        },
    )

    assert repository.preload_outfit(manifest, 'snow_slope_skier') is True
    qtbot.waitUntil(lambda: ready.count() == 1, timeout=2000)

    assert registry.calls == [
        ('snow_ferret', 'outfits/skier/idle_atlas.png'),
    ]
    assert repository.shutdown()


def test_outfit_request_completes_only_after_all_idle_resources_decode(
    qtbot,
    tmp_path,
):
    path = tmp_path / 'atlas.png'
    _write_image(path)
    repository = PetAssetRepository(_Registry(path))
    ready = QSignalSpy(repository.outfit_preload_ready)
    failed = QSignalSpy(repository.outfit_preload_failed)
    manifest = SimpleNamespace(
        pet_id='snow_ferret',
        outfits={
            'skier': SimpleNamespace(
                actions={
                    'idle': SimpleNamespace(
                        frames=(
                            SimpleNamespace(path='outfits/skier/idle_a.png'),
                            SimpleNamespace(path='outfits/skier/idle_b.png'),
                        )
                    )
                }
            )
        },
    )

    assert repository.request_outfit_preload(manifest, 'skier', 17) is True
    assert ready.count() == 0
    qtbot.waitUntil(lambda: ready.count() == 1, timeout=2000)

    assert list(ready.at(0)) == [17, 'snow_ferret', 'skier']
    assert failed.count() == 0
    assert repository.shutdown()


def test_outfit_request_reports_decode_failure_without_success(qtbot, tmp_path):
    path = tmp_path / 'broken.png'
    path.write_bytes(b'not a png')
    repository = PetAssetRepository(_Registry(path))
    ready = QSignalSpy(repository.outfit_preload_ready)
    failed = QSignalSpy(repository.outfit_preload_failed)
    frame = SimpleNamespace(path='outfits/skier/idle.png')
    manifest = SimpleNamespace(
        pet_id='snow_ferret',
        outfits={
            'skier': SimpleNamespace(
                actions={'idle': SimpleNamespace(frames=(frame,))}
            )
        },
    )

    assert repository.request_outfit_preload(manifest, 'skier', 23) is True
    qtbot.waitUntil(lambda: failed.count() == 1, timeout=2000)

    assert list(failed.at(0)) == [
        23,
        'snow_ferret',
        'skier',
        'outfits/skier/idle.png',
    ]
    assert ready.count() == 0
    assert repository.shutdown()


def test_lru_cache_honours_entry_limit(qtbot, tmp_path):
    first = tmp_path / 'first.png'
    second = tmp_path / 'second.png'
    _write_image(first)
    _write_image(second, '#F2A65A')
    registry = _Registry(first)
    repository = PetAssetRepository(registry, cache_limit=1)
    ready = QSignalSpy(repository.resource_ready)

    repository.load_frame('snow_ferret', 'sprites/first.png')
    qtbot.waitUntil(lambda: ready.count() == 1, timeout=2000)
    registry.path = second
    repository.load_frame('snow_ferret', 'sprites/second.png')
    qtbot.waitUntil(lambda: ready.count() == 2, timeout=2000)

    assert repository.cache_entry_count == 1
    assert repository.load_frame('snow_ferret', 'sprites/second.png') is not None
    assert repository.shutdown()
