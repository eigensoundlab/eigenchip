# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""skyline - reduce by pitch alone.

Lead = the highest line, bass = the lowest line of what is left, inner = the
highest line of what is left after that. Channels and instruments are ignored.

Strong when the tune really is on top (most piano and vocal arrangements).
Fails whenever accompaniment sits above the melody.
"""
from __future__ import annotations

from ..ir import Arrangement
from .common import line, map_drums, voice, without

NAME = "skyline"
SUMMARY = "Pitch only: top line, bottom line, then the top of the rest."


def arrange(grid, voices=3):
    notes = grid.pitched
    lead, used = line(notes, top=True)
    rest = without(notes, used)
    out = [voice("lead", lead)]
    if voices >= 2:
        bass, used = line(rest, top=False)
        rest = without(rest, used)
        out.append(voice("bass", bass))
    if voices >= 3:
        inner, _used = line(rest, top=True)
        out.append(voice("inner", inner))
    return Arrangement(out, map_drums(grid.drums), NAME)
