"""Pure domain models and policies for context-aware behaviour."""

from opencareyes.domain.context import (
    AppRule,
    AutoPausePreferences,
    ContextSnapshot,
    FeatureSuppression,
    SuppressionDecision,
)
from opencareyes.domain.policy import AutoPausePolicy
from opencareyes.domain.runtime import (
    DesiredEffectState,
    DisplayPreview,
    ReconcileFailure,
    ReconcileResult,
    RuntimeIntent,
)

__all__ = [
    "AppRule",
    "AutoPausePolicy",
    "AutoPausePreferences",
    "ContextSnapshot",
    "FeatureSuppression",
    "SuppressionDecision",
    "DesiredEffectState",
    "DisplayPreview",
    "ReconcileFailure",
    "ReconcileResult",
    "RuntimeIntent",
]
