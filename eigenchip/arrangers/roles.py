# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""roles - work out which channel is the melody and which is the bass.

Each channel is scored from simple statistics. A melody tends to be monophonic,
to keep moving and to use many different pitches; a bass is the lowest
monophonic channel. The lead is then taken from the lead channel only, so
accompaniment that climbs above the tune cannot steal it.

With a single channel (a piano piece, say) there are no roles to find and the
arranger falls back to skyline.
"""
from __future__ import annotations

from ..ir import Arrangement
from . import skyline
from .common import channel_stats, line, map_drums, more_lines, voice, without

NAME = "roles"
SUMMARY = "Guess melody and bass channels from statistics; top line of the rest."


def score_lead(st, mean_all, loud_all=None):
    louder = 0.0 if loud_all is None else max(-1.0, min(1.0, (st["velocity"] - loud_all) / 24.0))
    return (1.2 * st["monophony"]
            + 1.0 * louder                                     # the tune is played to be heard
            + 0.8 * min(1.0, st["distinct"] / 8.0)
            + 0.6 * st["movement"]
            + 1.0 * st.get("stepwise", 0.5)                     # a tune walks; a broken chord leaps
            + 0.9 * min(1.0, st["density"] / 1.5)             # a tune has things to say; a pad holds still
            + 0.4 * max(-1.0, min(1.0, (st["mean_pitch"] - mean_all) / 12.0))
            + 0.3 * st["coverage"])


def pick_roles(grid):
    """Return ``(lead_channel, bass_channel, stats)``; either may be None."""
    stats = channel_stats(grid)
    if len(stats) < 2:
        return None, None, stats
    mean_all = sum(s["mean_pitch"] * s["notes"] for s in stats.values()) / float(sum(s["notes"] for s in stats.values()))
    lowest = min(stats, key=lambda ch: stats[ch]["mean_pitch"])
    bass = lowest if (stats[lowest]["monophony"] >= 0.6 and stats[lowest]["mean_pitch"] < 55
                      and len(stats) >= 3) else None
    candidates = [ch for ch in stats if ch != bass]
    loud_all = sum(stats[ch]["velocity"] * stats[ch]["notes"] for ch in candidates) / float(
        sum(stats[ch]["notes"] for ch in candidates))
    lead = max(candidates, key=lambda ch: score_lead(stats[ch], mean_all, loud_all))
    known = grid.info.get("lead_channel")           # a reader that followed the tune itself says where it put it
    if known in stats:
        lead, bass = known, (bass if bass != known else None)
    return lead, bass, stats


def _split(grid):
    lead_ch, bass_ch, stats = pick_roles(grid)
    if lead_ch is None:
        return None
    if grid.info.get("lines_guessed"):
        bass_ch = None      # guessed lines are good enough to find the tune; the bass is safer taken from the bottom
    notes = grid.pitched
    lead, used = line([n for n in notes if n.channel == lead_ch], top=True)
    rest = without(notes, used)
    bass = []
    if bass_ch is not None:
        bass, used = line([n for n in rest if n.channel == bass_ch], top=False)
        rest = without(rest, used)
    else:
        bass, used = line(rest, top=False)
        rest = without(rest, used)
    return lead, bass, rest, {"lead_channel": lead_ch, "bass_channel": bass_ch}


def arrange(grid, voices=3):
    parts = _split(grid)
    if parts is None:
        arr = skyline.arrange(grid, voices)
        arr.name = NAME
        arr.notes["fallback"] = "skyline (single channel)"
        return arr
    lead, bass, rest, remarks = parts
    out = [voice("lead", lead)]
    if voices >= 2:
        out.append(voice("bass", bass))
    if voices >= 3:
        out += more_lines(rest, voices - 2)[0]
    return Arrangement(out, map_drums(grid.drums), NAME, remarks)
