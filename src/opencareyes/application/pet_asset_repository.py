'''Asynchronous, bounded image decoding for declarative pet packs.'''

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtGui import QImage, QImageReader


class _DecodeSignals(QObject):
    finished = Signal(str, str, object)


class _CatalogSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


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


class _CatalogTask(QRunnable):
    def __init__(self, registry):
        super().__init__()
        self.registry = registry
        self.signals = _CatalogSignals()

    @Slot()
    def run(self) -> None:
        try:
            entries = tuple(self.registry.available_pets())
        except Exception as exc:
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(entries)


class PetAssetRepository(QObject):
    '''Decode pet images off the GUI thread and retain a small LRU cache.'''

    resource_ready = Signal(str, str)
    resource_failed = Signal(str, str)
    outfit_preload_ready = Signal(int, str, str)
    outfit_preload_failed = Signal(int, str, str, str)
    catalog_ready = Signal(object)
    catalog_failed = Signal(str)

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
        self._outfit_preloads: dict[int, dict[str, object]] = {}
        self._outfit_waiters: dict[tuple[str, str], set[int]] = {}
        self._catalog_task: _CatalogTask | None = None
        self._catalog_entries: tuple | None = None
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)

    @property
    def pending_count(self) -> int:
        return len(self._tasks)

    @property
    def cache_bytes(self) -> int:
        return self._cache_bytes

    @property
    def cache_entry_count(self) -> int:
        return len(self._cache)

    @property
    def catalog_entries(self) -> tuple | None:
        return self._catalog_entries

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

    def preload_outfit(self, manifest, outfit_id: str) -> bool:
        '''Schedule only the selected outfit's idle resources.'''

        pet_id, _selected, paths = self._outfit_idle_paths(manifest, outfit_id)
        for resource_path in paths:
            self._schedule(pet_id, resource_path)
        return bool(paths)

    def request_outfit_preload(
        self,
        manifest,
        outfit_id: str,
        request_id: int,
    ) -> bool:
        '''Publish success only after every selected idle resource is decoded.'''

        request = int(request_id)
        if request in self._outfit_preloads:
            return False
        pet_id, selected, paths = self._outfit_idle_paths(manifest, outfit_id)
        if not pet_id or not selected or not paths:
            return False

        pending = {
            path
            for path in paths
            if (pet_id, path) not in self._cache
        }
        self._outfit_preloads[request] = {
            'pet_id': pet_id,
            'outfit_id': selected,
            'pending': pending,
        }
        if not pending:
            self._finish_outfit_preload(request)
            return True

        for resource_path in tuple(pending):
            key = (pet_id, resource_path)
            self._outfit_waiters.setdefault(key, set()).add(request)
            self._schedule(*key)
        return True

    def request_catalog(self) -> bool:
        '''Validate non-active bundled packs once, off the GUI thread.'''

        if self._catalog_entries is not None or self._catalog_task is not None:
            return False
        task = _CatalogTask(self._registry)
        task.signals.finished.connect(self._on_catalog_ready)
        task.signals.failed.connect(self._on_catalog_failed)
        self._catalog_task = task
        self._pool.start(task)
        return True

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
            self._resolve_outfit_resource(key, succeeded=False)
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
            self._resolve_outfit_resource(key, succeeded=False)
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
        self._resolve_outfit_resource(key, succeeded=True)

    @staticmethod
    def _outfit_idle_paths(manifest, outfit_id: str) -> tuple[str, str, set[str]]:
        selected = str(outfit_id).strip().lower()
        outfits = getattr(manifest, 'outfits', {})
        outfit = outfits.get(selected) if hasattr(outfits, 'get') else None
        actions = getattr(outfit, 'actions', {})
        idle = actions.get('idle') if hasattr(actions, 'get') else None
        if idle is None:
            return '', selected, set()
        pet_id = str(getattr(manifest, 'pet_id', ''))
        paths = {
            str(getattr(frame, 'path', ''))
            for frame in getattr(idle, 'frames', ())
            if getattr(frame, 'path', '')
        }
        return pet_id, selected, paths

    def _resolve_outfit_resource(
        self,
        key: tuple[str, str],
        *,
        succeeded: bool,
    ) -> None:
        request_ids = tuple(self._outfit_waiters.pop(key, ()))
        for request_id in request_ids:
            request = self._outfit_preloads.get(request_id)
            if request is None:
                continue
            if not succeeded:
                self._fail_outfit_preload(request_id, key[1])
                continue
            pending = request.get('pending')
            if isinstance(pending, set):
                pending.discard(key[1])
                if not pending:
                    self._finish_outfit_preload(request_id)

    def _finish_outfit_preload(self, request_id: int) -> None:
        request = self._outfit_preloads.pop(int(request_id), None)
        if request is None:
            return
        self.outfit_preload_ready.emit(
            int(request_id),
            str(request.get('pet_id', '')),
            str(request.get('outfit_id', '')),
        )

    def _fail_outfit_preload(self, request_id: int, resource_path: str) -> None:
        request = self._outfit_preloads.pop(int(request_id), None)
        if request is None:
            return
        for waiters in self._outfit_waiters.values():
            waiters.discard(int(request_id))
        self.outfit_preload_failed.emit(
            int(request_id),
            str(request.get('pet_id', '')),
            str(request.get('outfit_id', '')),
            str(resource_path),
        )

    @Slot(object)
    def _on_catalog_ready(self, entries) -> None:
        self._catalog_task = None
        self._catalog_entries = tuple(entries or ())
        self.catalog_ready.emit(self._catalog_entries)

    @Slot(str)
    def _on_catalog_failed(self, message: str) -> None:
        self._catalog_task = None
        self.catalog_failed.emit(str(message))
