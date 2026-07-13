"""Explicit, privacy-minimal GitHub release checks."""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from opencareyes.constants import APP_VERSION
from opencareyes.state import UpdateState


RELEASE_API_URL = "https://api.github.com/repos/Odyphus/OpenCareEyes/releases/latest"
_MAX_RESPONSE_BYTES = 1024 * 1024
_STABLE_VERSION = re.compile(
    r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:\+[0-9A-Za-z.-]+)?$"
)
_PRERELEASE_VERSION = re.compile(
    r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"-[0-9A-Za-z.-]+(?:\+[0-9A-Za-z.-]+)?$"
)


class ManualUpdateService:
    """Check once only when :meth:`check_for_updates` is called by the user."""

    def __init__(
        self,
        current_version: str = APP_VERSION,
        *,
        opener=urlopen,
    ) -> None:
        self._current_version = current_version
        self._opener = opener
        self._state = UpdateState("idle", current_version)

    @property
    def state(self) -> UpdateState:
        return self._state

    def check_for_updates(self) -> UpdateState:
        self._state = UpdateState("checking", self._current_version)
        current = _parse_stable_version(self._current_version)
        if current is None:
            return self._finish(UpdateState("failed", self._current_version))

        request = Request(
            RELEASE_API_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "OpenCareEyes-UpdateCheck",
            },
        )
        response = None
        try:
            response = self._opener(request, timeout=5.0)
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                raise ValueError("Release response is too large")
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            return self._finish(UpdateState("failed", self._current_version))
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

        if not isinstance(payload, dict):
            return self._finish(UpdateState("failed", self._current_version))
        if payload.get("draft") is True or payload.get("prerelease") is True:
            return self._finish(UpdateState("up_to_date", self._current_version))

        latest_text = payload.get("tag_name")
        if isinstance(latest_text, str) and _PRERELEASE_VERSION.fullmatch(
            latest_text.strip()
        ):
            return self._finish(UpdateState("up_to_date", self._current_version))
        latest = _parse_stable_version(latest_text)
        if latest is None:
            return self._finish(UpdateState("failed", self._current_version))
        normalized_latest = ".".join(str(part) for part in latest)
        release_url = _validated_release_url(payload.get("html_url"))
        if latest > current:
            if release_url is None:
                return self._finish(UpdateState("failed", self._current_version))
            return self._finish(
                UpdateState(
                    "available",
                    self._current_version,
                    normalized_latest,
                    release_url,
                )
            )
        return self._finish(
            UpdateState(
                "up_to_date",
                self._current_version,
                normalized_latest,
                release_url or "",
            )
        )

    # Compact compatibility alias for UI adapters.
    check = check_for_updates

    def _finish(self, state: UpdateState) -> UpdateState:
        self._state = state
        return state


def _parse_stable_version(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = _STABLE_VERSION.fullmatch(value.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def _validated_release_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        return None
    prefix = "/Odyphus/OpenCareEyes/releases/"
    if not parsed.path.startswith(prefix):
        return None
    return value
