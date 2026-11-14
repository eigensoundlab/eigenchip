# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""roles-arp - melody and bass by role, everything else as arpeggiated chords.

The oldest trick in chip music: a channel that cannot play a chord plays its
notes one after another, fast. Here whatever is left after lead and bass is
summarised as one chord per half bar and handed to an arpeggio voice.

Keeps far more of the harmony than a third melodic line can, at the price of
the accompaniment's own rhythm.
"""
from __future__ import annotations

from ..ir import Arrangement
from . import roles
from .common import chord_voice, line, map_drums, more_lines, voice, without

NAME = "roles-arp"
SUMMARY = "Melody and bass by role; the rest as one arpeggiated chord per half bar."


def arrange(grid, voices=3):
    parts = roles._split(grid)
    remarks = {}
    if parts is None:                       # one channel: split by pitch instead
        notes = grid.pitched
        lead, used = line(notes, top=True)
        rest = without(notes, used)
        bass, used = line(rest, top=False)
        rest = without(rest, used)
        remarks["fallback"] = "pitch split (single channel)"
    else:
        lead, bass, rest, remarks = parts
    out = [voice("lead", lead)]
    if voices >= 2:
        out.append(voice("bass", bass))
    if voices >= 3:                         # beyond three, further lines come first and the chords take the rest
        lines, rest = more_lines(rest, voices - 3)
        out += lines
        out.append(voice("chords", chord_voice(rest, grid)))
    return Arrangement(out, map_drums(grid.drums), NAME, remarks)
