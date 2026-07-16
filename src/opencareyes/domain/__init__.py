"""Pure domain models and policies for context-aware behaviour."""

from opencareyes.domain.context import (
    AppRule,
    AutoPausePreferences,
    ContextSnapshot,
    FeatureSuppression,
    SuppressionDecision,
)
from opencareyes.domain.policy import AutoPausePolicy
from opencareyes.domain.pet import (
    APPEARANCE_SLOTS,
    REQUIRED_ACTIONS,
    PetAction,
    PetAppearance,
    PetBehavior,
    PetCatalogEntry,
    PetEvent,
    PetEventPriority,
    PetFrame,
    PetPackManifest,
    PetPersonality,
    PetVisualTheme,
    PetState,
    priority_for_event_kind,
)
from opencareyes.domain.runtime import (
    DesiredEffectState,
    DisplayPreview,
    ReconcileFailure,
    ReconcileResult,
    RuntimeIntent,
)

__all__ = [
    'APPEARANCE_SLOTS',
    'REQUIRED_ACTIONS',
    'PetAction',
    'PetAppearance',
    'PetBehavior',
    'PetCatalogEntry',
    'PetEvent',
    'PetEventPriority',
    'PetFrame',
    'PetPackManifest',
    'PetPersonality',
    'PetVisualTheme',
    'PetState',
    'priority_for_event_kind',
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
