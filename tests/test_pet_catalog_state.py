'''Tests for species-neutral pet catalog presentation.'''

from dataclasses import FrozenInstanceError

import pytest

from opencareyes.state import (
    CompanionPresentationSnapshot,
    PetCatalogEntryState,
    PetCatalogState,
    PetOutfitEntryState,
    PetState,
    PetWardrobeState,
)


def test_active_display_name_follows_selected_pack():
    catalog = PetCatalogState(
        available_pets=(
            PetCatalogEntryState('snow_ferret', '鼬鼬'),
            PetCatalogEntryState('tiny_bird', '啾啾'),
        ),
        active_pet_id='tiny_bird',
    )

    assert catalog.active_display_name == '啾啾'


def test_unknown_active_pet_uses_species_neutral_fallback():
    catalog = PetCatalogState(active_pet_id='future_pet')

    assert catalog.active_display_name == '伙伴'


def test_wardrobe_state_and_outfit_projection_are_immutable():
    wardrobe = PetWardrobeState(
        available_outfits=(
            PetOutfitEntryState(
                outfit_id='snow_slope_skier',
                display_name='雪坡滑雪客',
            ),
        ),
        mode='outfit',
        selected_outfit_id='snow_slope_skier',
        effective_outfit_id='snow_slope_skier',
    )
    companion = PetState(outfit_id='snow_slope_skier')
    presentation = CompanionPresentationSnapshot(outfit_id='snow_slope_skier')

    assert wardrobe.available_outfits[0].display_name == '雪坡滑雪客'
    assert companion.outfit_id == presentation.outfit_id == 'snow_slope_skier'
    with pytest.raises(FrozenInstanceError):
        wardrobe.mode = 'automatic'
