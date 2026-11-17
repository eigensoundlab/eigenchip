# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Building blocks shared by the arrangers."""
from __future__ import annotations

from ..ir import Voice

INSTRUMENTS = {
    "lead": {"wave": "square", "duty": 0.25, "attack": 0.01, "decay": 0.1, "sustain": 0.6,
             "release": 0.1, "vibrato": [5, 0.005], "volume": 0.32},
    "inner": {"wave": "soft", "attack": 0.01, "decay": 0.12, "sustain": 0.5, "release": 0.1, "volume": 0.16},
    "bass": {"wave": "triangle", "attack": 0.01, "decay": 0.1, "sustain": 0.8, "release": 0.08, "volume": 0.5},
    "chords": {"wave": "triangle", "attack": 0.005, "decay": 0.1, "sustain": 0.35, "release": 0.08,
               "volume": 0.2, "arp": 1, "gate": 1.0},
    "kit": {"wave": "drums", "volume": 0.55},
}

# Other sounds for the tune, to choose when the one an arranger or a style gives it is too sharp.  Each replaces
# the lead's instrument whole.  ``strings`` uses detune, a filter and a room: CLIo 2.2.2.
LEADS = {
    "soft": {"about": "Rounded and quieter: a tune that does not cut.",
             "sound": {"wave": "soft", "attack": 0.03, "decay": 0.12, "sustain": 0.65, "release": 0.25,
                       "vibrato": [5, 0.004], "lowpass": 0.3, "volume": 0.24}},
    "flute": {"about": "A plain, breathy tone.",
              "sound": {"wave": "sine", "attack": 0.05, "decay": 0.1, "sustain": 0.8, "release": 0.3,
                        "vibrato": [5, 0.005], "volume": 0.34}},
    "strings": {"about": "A section of strings, a little slow to speak.",
                "sound": {"wave": "saw", "detune": 8, "attack": 0.1, "decay": 0.15, "sustain": 0.8, "release": 0.4,
                          "filter": [700, 2600, 0.1, 0.4], "room": 0.4, "volume": 0.32}},
}

# General MIDI percussion -> the five drum sounds of the target
_GM_DRUMS = {35: "k", 36: "k", 37: "s", 38: "s", 39: "c", 40: "s", 41: "t", 43: "t", 45: "t", 47: "t",
             48: "t", 50: "t", 42: "h", 44: "h", 46: "o", 49: "o", 51: "h", 52: "o", 53: "h", 55: "o",
             57: "o", 59: "h", 54: "h", 56: "h", 69: "h", 70: "h", 75: "c", 76: "h", 77: "h"}
_DRUM_ORDER = "kscthob"


def map_drums(notes):
    """Drum notes -> ``[(step, ["k", "h"]), ...]``."""
    by_step = {}
    for n in notes:
        hit = _GM_DRUMS.get(n.pitch)
        if hit:
            by_step.setdefault(n.start, set()).add(hit)
    out = []
    for step in sorted(by_step):
        hits = by_step[step]
        if "o" in hits:
            hits.discard("h")                   # an open hat hides a closed one
        out.append((step, sorted(hits, key=_DRUM_ORDER.index)))
    return out


def line(notes, top=True):
    """Reduce notes to one monophonic line, choosing at every onset.

    The classic *skyline* idea, decided at note onsets: a new note takes over
    if nothing is sounding or if it is at least as high (``top``) / as low as
    the note it would interrupt. Returns ``(events, used_notes)``.
    """
    sign = 1 if top else -1
    by_start = {}
    for n in notes:
        by_start.setdefault(n.start, []).append(n)
    events, used, cur = [], [], None
    for t in sorted(by_start):
        cand = max(by_start[t], key=lambda n: (sign * n.pitch, n.dur))
        if cur is None or cur.end <= t or sign * cand.pitch >= sign * cur.pitch:
            if cur is not None and cur.end > t:
                s, _d, p = events[-1]
                events[-1] = (s, t - s, p)
            events.append((cand.start, cand.dur, [cand.pitch]))
            used.append(cand)
            cur = cand
    return events, used


def without(notes, used):
    ids = {id(n) for n in used}
    return [n for n in notes if id(n) not in ids]


MAX_VOICES = 6


def more_lines(rest, count):
    """Peel ``count`` further lines off the top of ``rest``: ``([Voice, ...], what is left)``."""
    out = []
    for i in range(max(0, count)):
        events, used = line(rest, top=True)
        if not events:
            break
        out.append(voice("inner", events, "inner" if i == 0 else "inner%d" % (i + 1)))
        rest = without(rest, used)
    return out, rest


def voice(role, events, name=None):
    return Voice(name or role, role, events, INSTRUMENTS[role])


def chord_voice(notes, grid, window=None, size=3, low=48, high=72):
    """Summarise notes as one chord per window (to be played as an arpeggio).

    For each window the pitch classes that sound longest are kept, re-voiced
    into one register so the arpeggio does not leap about.
    """
    window = window or max(1, grid.steps_per_bar // 2)
    end = max((n.end for n in notes), default=0)
    events = []
    for start in range(0, end, window):
        weight = {}
        for n in notes:
            overlap = min(n.end, start + window) - max(n.start, start)
            if overlap > 0:
                weight[n.pitch % 12] = weight.get(n.pitch % 12, 0) + overlap * (0.5 + n.vel / 254.0)
        if not weight:
            continue
        pcs = sorted(weight, key=lambda pc: -weight[pc])[:size]
        pitches = []
        for pc in pcs:
            p = low + (pc - low) % 12
            pitches.append(p if p <= high else p - 12)
        pitches.sort()
        if events and events[-1][2] == pitches and events[-1][0] + events[-1][1] == start:
            s, d, p = events[-1]
            events[-1] = (s, d + window, p)             # same chord carries on
        else:
            events.append((start, window, pitches))
    return events


def channel_stats(grid):
    """Per-channel statistics used to guess which channel plays which role."""
    stats = {}
    length = max(1, grid.length)
    for ch in grid.channels():
        notes = [n for n in grid.pitched if n.channel == ch]
        steps = {}
        for n in notes:
            for t in range(n.start, n.end):
                steps[t] = steps.get(t, 0) + 1
        onsets = sorted({n.start for n in notes})
        mono = sum(1 for c in steps.values() if c == 1) / float(len(steps) or 1)
        pitches = [n.pitch for n in notes]
        moves = sum(1 for a, b in zip(pitches, pitches[1:]) if a != b) / float(max(1, len(pitches) - 1))
        tops = {}
        for n in notes:
            tops[n.start] = max(tops.get(n.start, 0), n.pitch)
        tune = [tops[t] for t in sorted(tops)]
        jumps = [abs(a - b) for a, b in zip(tune, tune[1:]) if a != b]
        stepwise = sum(1 for j in jumps if j <= 2) / float(len(jumps)) if jumps else 0.5
        stats[ch] = {
            "notes": len(notes),
            "mean_pitch": sum(pitches) / float(len(pitches)),
            "monophony": mono,                                  # share of sounding time with one note
            "coverage": len(steps) / float(length),             # share of the piece it sounds in
            "density": len(onsets) / (length / float(grid.steps_per_beat)),    # onsets per beat
            "distinct": len(set(pitches)),
            "movement": moves,                                  # how often consecutive notes differ
            "stepwise": stepwise,                               # share of its moves that are steps, not leaps
            "velocity": sum(n.vel for n in notes) / float(len(notes)),
        }
    return stats
