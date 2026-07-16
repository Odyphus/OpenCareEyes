'''Build the bundled original companion chime as deterministic PCM WAV.'''

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


SAMPLE_RATE = 44_100
DURATION_SECONDS = 0.62


def envelope(seconds: float) -> float:
    attack = min(1.0, seconds / 0.012)
    decay = math.exp(-5.8 * seconds)
    release_start = DURATION_SECONDS - 0.09
    release = 1.0 if seconds < release_start else max(
        0.0,
        (DURATION_SECONDS - seconds) / (DURATION_SECONDS - release_start),
    )
    return attack * decay * release


def sample(seconds: float) -> float:
    # A short two-note bell synthesized from inharmonic partials. It is generated
    # locally from this formula and does not derive from a recording or melody.
    second_note = max(0.0, seconds - 0.16)
    first = sum(
        amplitude * math.sin(2 * math.pi * frequency * seconds)
        for frequency, amplitude in ((1174.66, 0.55), (2349.32, 0.20), (3104.0, 0.10))
    )
    second = 0.0
    if seconds >= 0.16:
        second = sum(
            amplitude * math.sin(2 * math.pi * frequency * second_note)
            for frequency, amplitude in ((1567.98, 0.42), (3135.96, 0.15), (4140.0, 0.07))
        ) * math.exp(-7.0 * second_note)
    return 0.62 * envelope(seconds) * (first + second)


def build(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    frame_count = round(SAMPLE_RATE * DURATION_SECONDS)
    frames = bytearray()
    for index in range(frame_count):
        value = max(-1.0, min(1.0, sample(index / SAMPLE_RATE)))
        frames.extend(struct.pack('<h', round(value * 32767)))
    with wave.open(str(output), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(frames)


if __name__ == '__main__':
    repository = Path(__file__).resolve().parents[1]
    build(repository / 'assets' / 'pets' / 'snow_ferret' / 'sounds' / 'chime.wav')
