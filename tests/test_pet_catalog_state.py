'''Tests for species-neutral pet catalog presentation.'''

from opencareyes.state import PetCatalogEntryState, PetCatalogState


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
