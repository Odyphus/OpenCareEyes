"""Unit tests for the Tanner Helland color temperature algorithm."""

import pytest

from opencareyes.core.color_temp import kelvin_to_rgb


class TestKelvinToRgb:
    """Tests for kelvin_to_rgb conversion."""

    def test_6500k_returns_near_white(self):
        """6500K (daylight) should produce approximately (1.0, 1.0, 1.0)."""
        r, g, b = kelvin_to_rgb(6500)
        assert r == pytest.approx(1.0, abs=0.05)
        assert g == pytest.approx(1.0, abs=0.05)
        assert b == pytest.approx(1.0, abs=0.05)

    def test_1000k_very_low_blue(self):
        """1000K should have very low blue and green, high red."""
        r, g, b = kelvin_to_rgb(1000)
        assert r == 1.0
        assert b == 0.0
        assert g < 0.3

    def test_4500k_reduced_blue(self):
        """4500K (typical night filter) should have reduced blue."""
        r, g, b = kelvin_to_rgb(4500)
        assert r > b, "Red should be greater than blue at 4500K"
        assert g > b, "Green should be greater than blue at 4500K"

    def test_all_values_clamped_0_to_1(self):
        """All RGB values must be in [0.0, 1.0] for any valid temperature."""
        for kelvin in range(1000, 6600, 100):
            r, g, b = kelvin_to_rgb(kelvin)
            assert 0.0 <= r <= 1.0, f"Red out of range at {kelvin}K: {r}"
            assert 0.0 <= g <= 1.0, f"Green out of range at {kelvin}K: {g}"
            assert 0.0 <= b <= 1.0, f"Blue out of range at {kelvin}K: {b}"

    def test_temperature_monotonicity_blue(self):
        """Blue channel should generally increase as temperature rises."""
        prev_b = 0.0
        for kelvin in range(2000, 6600, 500):
            _, _, b = kelvin_to_rgb(kelvin)
            assert b >= prev_b, (
                f"Blue should not decrease: {prev_b} -> {b} at {kelvin}K"
            )
            prev_b = b

    def test_boundary_1900k_zero_blue(self):
        """At 1900K (temp/100 = 19), blue should be 0."""
        _, _, b = kelvin_to_rgb(1900)
        assert b == 0.0

    def test_boundary_6600k_full_blue(self):
        """At 6600K (temp/100 = 66), blue should be 1.0."""
        _, _, b = kelvin_to_rgb(6600)
        assert b == 1.0

    def test_3400k_night_mode(self):
        """3400K (night preset) should produce warm tones."""
        r, g, b = kelvin_to_rgb(3400)
        assert r > g > b, "Night mode should be warm: R > G > B"
