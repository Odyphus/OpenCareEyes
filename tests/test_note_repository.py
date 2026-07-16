"""Tests for bounded, atomic local note storage."""

import itertools
import json
from datetime import datetime, timezone

import pytest

import opencareyes.application.note_repository as note_module
from opencareyes.application.note_repository import (
    NoteLimitError,
    NoteRepository,
    NoteRepositoryError,
)


def test_add_update_delete_round_trip_utf8(tmp_path):
    path = tmp_path / "notes.json"
    now = [datetime(2026, 7, 15, tzinfo=timezone.utc)]
    repository = NoteRepository(path, now=lambda: now[0], id_factory=lambda: "note-1")

    created = repository.add("记得起来活动", title="下午")
    assert repository.list_notes() == (created,)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert raw["notes"][0]["text"] == "记得起来活动"

    now[0] = datetime(2026, 7, 15, 1, tzinfo=timezone.utc)
    updated = repository.update("note-1", text="喝水并活动", title="下午")
    assert updated.created_at == created.created_at
    assert updated.updated_at != created.updated_at
    assert repository.delete("note-1") is True
    assert repository.delete("note-1") is False
    assert repository.list_notes() == ()


def test_repository_enforces_fifty_note_limit(tmp_path):
    ids = (f"note-{index}" for index in itertools.count())
    repository = NoteRepository(tmp_path / "notes.json", id_factory=lambda: next(ids))
    for index in range(50):
        repository.add(f"note {index}")

    with pytest.raises(NoteLimitError, match="50"):
        repository.add("one too many")


def test_atomic_replace_failure_preserves_original_file(tmp_path, monkeypatch):
    path = tmp_path / "notes.json"
    repository = NoteRepository(path, id_factory=lambda: "note-1")
    repository.add("original")
    original = path.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("disk failure")

    monkeypatch.setattr(note_module.os, "replace", fail_replace)
    with pytest.raises(NoteRepositoryError, match="保存失败"):
        repository.update("note-1", text="must not replace original")

    assert path.read_bytes() == original
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("content", ["not json", "{}", "{schema_version: 999, notes: []}"])
def test_corrupt_or_future_note_file_fails_closed(tmp_path, content):
    path = tmp_path / "notes.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(NoteRepositoryError):
        NoteRepository(path).list_notes()


def test_duplicate_generated_id_is_rejected(tmp_path):
    repository = NoteRepository(tmp_path / "notes.json", id_factory=lambda: "same")
    repository.add("first")
    with pytest.raises(NoteRepositoryError, match="唯一"):
        repository.add("second")
