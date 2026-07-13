"""Immutable runtime intent and reconciliation results."""

from __future__ import annotations

from dataclasses import dataclass, field

from opencareyes.domain.context import SuppressionDecision
from opencareyes.state import EffectivePolicyState


@dataclass(frozen=True, slots=True)
class DesiredEffectState:
    """User-owned desired feature state and effect parameters."""

    filter: bool = False
    dimmer: bool = False
    breaks: bool = False
    focus: bool = False
    color_temperature: int = 6500
    dim_level: int = 0
    focus_dim_level: int = 150


@dataclass(frozen=True, slots=True)
class DisplayPreview:
    """Ephemeral display values that must not become preferences."""

    color_temperature: int | None = None
    dim_level: int | None = None


@dataclass(frozen=True, slots=True)
class RuntimeIntent:
    """Complete effect intent consumed by :class:`EffectCoordinator`.

    ``schedule`` is intentionally opaque: the scheduler owns its policy, while
    the coordinator only needs it as part of the immutable intent boundary.
    """

    desired: DesiredEffectState = field(default_factory=DesiredEffectState)
    schedule: object | None = None
    suppression: SuppressionDecision = field(default_factory=SuppressionDecision)
    global_pause: bool = False
    preview: DisplayPreview | None = None


@dataclass(frozen=True, slots=True)
class ReconcileFailure:
    feature: str
    message: str


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    policy: EffectivePolicyState = field(default_factory=EffectivePolicyState)
    failures: tuple[ReconcileFailure, ...] = ()
    rollback_succeeded: bool = True
    pending_requests: tuple[object, ...] = ()

    @property
    def succeeded(self) -> bool:
        return not self.failures

    @property
    def settled(self) -> bool:
        return not self.pending_requests
