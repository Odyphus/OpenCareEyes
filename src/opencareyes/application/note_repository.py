'''Atomic local JSON storage for private companion notes.'''

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


SCHEMA_VERSION = 1
MAX_NOTES = 50
MAX_TITLE_LENGTH = 200
MAX_TEXT_LENGTH = 20_000


class NoteRepositoryError(RuntimeError):
    pass


class NoteLimitError(NoteRepositoryError):
    pass


@dataclass(frozen=True, slots=True)
class Note:
    note_id: str
    title: str
    text: str
    created_at: str
    updated_at: str


class NoteRepository:
    '''Persist at most 50 notes without logging or exposing their contents.'''

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        now: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._path = Path(path)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    def list_notes(self) -> tuple[Note, ...]:
        with self._lock:
            return tuple(self._load())

    def add(self, text: str, *, title: str = '') -> Note:
        _validate_content(title, text)
        with self._lock:
            notes = self._load()
            if len(notes) >= MAX_NOTES:
                raise NoteLimitError('最多只能保存 50 条便签。')
            note_id = self._id_factory()
            if not note_id or any(note.note_id == note_id for note in notes):
                raise NoteRepositoryError('无法生成唯一的便签标识。')
            timestamp = self._timestamp()
            note = Note(note_id, title, text, timestamp, timestamp)
            notes.append(note)
            self._write(notes)
            return note

    def update(self, note_id: str, *, text: str, title: str = '') -> Note:
        _validate_content(title, text)
        with self._lock:
            notes = self._load()
            for index, existing in enumerate(notes):
                if existing.note_id == note_id:
                    note = Note(
                        note_id=existing.note_id,
                        title=title,
                        text=text,
                        created_at=existing.created_at,
                        updated_at=self._timestamp(),
                    )
                    notes[index] = note
                    self._write(notes)
                    return note
            raise KeyError(note_id)

    def delete(self, note_id: str) -> bool:
        with self._lock:
            notes = self._load()
            remaining = [note for note in notes if note.note_id != note_id]
            if len(remaining) == len(notes):
                return False
            self._write(remaining)
            return True

    def clear(self) -> None:
        with self._lock:
            self._write([])

    def _timestamp(self) -> str:
        return self._now().isoformat()

    def _load(self) -> list[Note]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding='utf-8'))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NoteRepositoryError('便签文件无法读取。') from exc
        if not isinstance(raw, dict) or raw.get('schema_version') != SCHEMA_VERSION:
            raise NoteRepositoryError('便签文件版本无效。')
        records = raw.get('notes')
        if not isinstance(records, list) or len(records) > MAX_NOTES:
            raise NoteRepositoryError('便签文件内容无效。')
        try:
            notes = [Note(**record) for record in records if isinstance(record, dict)]
        except TypeError as exc:
            raise NoteRepositoryError('便签文件内容无效。') from exc
        if len(notes) != len(records) or len({note.note_id for note in notes}) != len(notes):
            raise NoteRepositoryError('便签文件内容无效。')
        for note in notes:
            try:
                _validate_content(note.title, note.text)
            except (TypeError, ValueError) as exc:
                raise NoteRepositoryError('便签文件内容无效。') from exc
            if not note.note_id or not note.created_at or not note.updated_at:
                raise NoteRepositoryError('便签文件内容无效。')
        return notes

    def _write(self, notes: list[Note]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            'schema_version': SCHEMA_VERSION,
            'notes': [asdict(note) for note in notes],
        }
        fd, temporary_name = tempfile.mkstemp(
            prefix=f'.{self._path.name}.', suffix='.tmp', dir=self._path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write('\n')
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise NoteRepositoryError('便签保存失败。') from exc


def _validate_content(title: object, text: object) -> None:
    if not isinstance(title, str) or not isinstance(text, str):
        raise TypeError('note title and text must be strings')
    if len(title) > MAX_TITLE_LENGTH:
        raise ValueError('note title is too long')
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError('note text is too long')
