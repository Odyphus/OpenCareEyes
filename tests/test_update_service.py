"""Tests for the explicit-only GitHub release check."""

import json

import pytest

from opencareyes.application.update_service import ManualUpdateService


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.closed = False

    def read(self, _limit):
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode("utf-8")

    def close(self):
        self.closed = True


def release(tag="v0.4.0", **overrides):
    payload = {
        "tag_name": tag,
        "html_url": f"https://github.com/Odyphus/OpenCareEyes/releases/tag/{tag}",
        "draft": False,
        "prerelease": False,
    }
    payload.update(overrides)
    return payload


def test_service_makes_no_request_until_explicit_check():
    calls = []
    service = ManualUpdateService("0.3.0", opener=lambda *args, **kwargs: calls.append(1))

    assert service.state.status == "idle"
    assert calls == []


def test_explicit_check_reports_stable_update_with_five_second_timeout():
    calls = []
    response = FakeResponse(release())

    def opener(request, *, timeout):
        calls.append((request, timeout))
        return response

    state = ManualUpdateService("0.3.0", opener=opener).check_for_updates()

    assert state.status == "available"
    assert state.latest_version == "0.4.0"
    assert state.release_url.endswith("/tag/v0.4.0")
    assert calls[0][1] == 5.0
    assert calls[0][0].full_url.endswith("/releases/latest")
    assert calls[0][0].get_header("User-agent") == "OpenCareEyes-UpdateCheck"
    assert response.closed is True


@pytest.mark.parametrize(
    "tag", ["v0.4.0", "v0.4.0+build.1", "0.3.0", "v0.2.9"]
)
def test_current_or_older_stable_release_is_up_to_date(tag):
    service = ManualUpdateService(
        "0.4.0", opener=lambda *_args, **_kwargs: FakeResponse(release(tag))
    )

    assert service.check().status == "up_to_date"


def test_prerelease_is_ignored():
    service = ManualUpdateService(
        "0.3.0",
        opener=lambda *_args, **_kwargs: FakeResponse(
            release("v0.4.0-rc.1", prerelease=True)
        ),
    )

    state = service.check()
    assert state.status == "up_to_date"
    assert state.latest_version == ""


def test_prerelease_tag_is_ignored_even_if_remote_flag_is_wrong():
    service = ManualUpdateService(
        "0.3.0",
        opener=lambda *_args, **_kwargs: FakeResponse(release("v0.4.0-rc.1")),
    )

    assert service.check().status == "up_to_date"


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        release("v0.4.0", html_url="https://example.com/release"),
        [],
    ],
)
def test_invalid_or_untrusted_release_payload_fails_closed(payload):
    service = ManualUpdateService(
        "0.3.0", opener=lambda *_args, **_kwargs: FakeResponse(payload)
    )

    assert service.check().status == "failed"


def test_offline_check_returns_error_without_raising():
    def offline(*_args, **_kwargs):
        raise OSError("offline")

    service = ManualUpdateService("0.3.0", opener=offline)

    assert service.check().status == "failed"
