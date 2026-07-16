'''Asynchronous, bounded image decoding for declarative pet packs.'''

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtGui import QImage, QImageReader


class _DecodeSignals(QObject):
    finished = Signal(str, str, object)


class _DecodeTask(QRunnable):
    def __init__(self, pet_id: str, resource_path: str, resolved_path: str):
        super().__init__()
        self.pet_id = pet_id
        self.resource_path = resource_path
        self.resolved_path = resolved_path
        self.signals = _DecodeSignals()

    @Slot()
    def run(self) -> None:
        reader = QImageReader(self.resolved_path)
        reader.setDecideFormatFromContent(True)
        image = reader.read()
        self.signals.finished.emit(
            self.pet_id,
            self.resource_path,
            image if not image.isNull() else None,
        )


class PetAssetRepository(QObject):
    '''Decode pet images off the GUI thread and retain a small LRU cache.'''

    resource_ready = Signal(str, str)
    resource_failed = Signal(str, str)

    def __init__(
        self,
        registry,
        parent: QObject | None = None,
        *,
        cache_limit: int = 12,
        cache_limit_bytes: int = 48 * 1024 * 1024,
    ) -> None:
        super().__init__(parent)
        self._registry = registry
        self._cache_limit = max(1, int(cache_limit))
        self._cache_limit_bytes = max(1, int(cache_limit_bytes))
        self._cache_bytes = 0
        self._cache: OrderedDict[tuple[str, str], QImage] = OrderedDict()
        self._tasks: dict[tuple[str, str], _DecodeTask] = {}
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)

    @property
    def pending_count(self) -> int:
        return len(self._tasks)

    @property
    def cache_bytes(self) -> int:
        return self._cache_bytes

    def resolve_resource(self, pet_id: str, resource_path: str):
        return self._registry.resolve_resource(pet_id, resource_path)

    def load_frame(self, pet_id: str, resource_path: str) -> QImage | None:
        key = (str(pet_id), str(resource_path))
        cached = self._cache.pop(key, None)
        if cached is not None:
            self._cache[key] = cached
            return QImage(cached)
        self._schedule(*key)
        return None

    def preload_manifest(self, manifest) -> None:
        pet_id = str(getattr(manifest, 'pet_id', ''))
        paths = {
            str(getattr(frame, 'path', ''))
            for action in getattr(manifest, 'actions', {}).values()
            for frame in getattr(action, 'frames', ())
            if getattr(frame, 'path', '')
        }
        for resource_path in paths:
            self._schedule(pet_id, resource_path)

    def clear(self, pet_id: str | None = None) -> None:
        if pet_id is None:
            self._cache.clear()
            self._cache_bytes = 0
            return
        selected = str(pet_id)
        for key in tuple(self._cache):
            if key[0] == selected:
                image = self._cache.pop(key)
                self._cache_bytes = max(0, self._cache_bytes - image.sizeInBytes())

    def shutdown(self, timeout_ms: int = 1000) -> bool:
        self._pool.clear()
        return bool(self._pool.waitForDone(max(0, int(timeout_ms))))

    def _schedule(self, pet_id: str, resource_path: str) -> None:
        key = (pet_id, resource_path)
        if not pet_id or not resource_path or key in self._cache or key in self._tasks:
            return
        try:
            resolved = self._registry.resolve_resource(pet_id, resource_path)
        except (FileNotFoundError, KeyError, OSError, TypeError, ValueError):
            self.resource_failed.emit(pet_id, resource_path)
            return
        task = _DecodeTask(pet_id, resource_path, str(resolved))
        task.signals.finished.connect(self._on_decoded)
        self._tasks[key] = task
        self._pool.start(task)

    @Slot(str, str, object)
    def _on_decoded(self, pet_id: str, resource_path: str, image) -> None:
        key = (pet_id, resource_path)
        self._tasks.pop(key, None)
        if not isinstance(image, QImage) or image.isNull():
            self.resource_failed.emit(pet_id, resource_path)
            return
        stored = QImage(image)
        self._cache[key] = stored
        self._cache_bytes += stored.sizeInBytes()
        while (
            len(self._cache) > self._cache_limit
            or self._cache_bytes > self._cache_limit_bytes
        ):
            _old_key, evicted = self._cache.popitem(last=False)
            self._cache_bytes = max(0, self._cache_bytes - evicted.sizeInBytes())
        self.resource_ready.emit(pet_id, resource_path)
