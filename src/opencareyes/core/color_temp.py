"""Tanner Helland algorithm: convert color temperature (Kelvin) to RGB multipliers."""

import math


def kelvin_to_rgb(kelvin: int) -> tuple[float, float, float]:
    """Convert color temperature (1000K-6500K) to RGB multipliers (0.0-1.0).

    Based on Tanner Helland's algorithm:
    https://tannerhelland.com/2012/09/18/convert-temperature-rgb-algorithm-code.html
    """
    temp = kelvin / 100.0

    # Red
    if temp <= 66:
        r = 1.0
    else:
        r = 329.6987 * ((temp - 60) ** -0.1332)
        r = max(0.0, min(255.0, r)) / 255.0

    # Green
    if temp <= 66:
        g = 99.4708 * math.log(temp) - 161.1196
    else:
        g = 288.1222 * ((temp - 60) ** -0.0755)
    g = max(0.0, min(255.0, g)) / 255.0

    # Blue
    if temp >= 66:
        b = 1.0
    elif temp <= 19:
        b = 0.0
    else:
        b = 138.5177 * math.log(temp - 10) - 305.0448
        b = max(0.0, min(255.0, b)) / 255.0

    return (r, g, b)
