# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Tidying a transcription before anything is built on it.

A transcriber makes characteristic mistakes: a held note cut in two, a faint
copy of a note a semitone beside it, a spray of short notes where something
slid or hissed.  Each rule here removes one kind of mistake - and, sometimes,
a real note that looked like one.  The modes say how much of that risk to take:

``off``     leave the transcription as it is
``light``   only what is very likely wrong: fragments, semitone shadows, short
            faint notes sitting on a drum hit, and what a detected sweep left behind
``strict``  also faint short notes and very short ones, and no more than six
            notes at once.  A cleaner page with holes in it.

Notes are ``(onset, offset, pitch, strength)`` in seconds.
"""
from __future__ import annotations

MODES = ("off", "light", "strict")


def clean(notes, mode="light", effects=None, hits=None):
    """Return the notes that survive the rules of ``mode``.

    ``effects`` are those found by ``find_effects`` and ``hits`` the drum hits
    found by ``find_drums``; both tell the rules where not to trust short notes.
    """
    if mode not in MODES:
        raise ValueError("Unknown cleaning mode '%s'. Choose from: %s" % (mode, ", ".join(MODES)))
    notes = sorted(notes)
    if mode == "off" or not notes:
        return notes
    strict = mode == "strict"
    notes = _join_fragments(notes, 0.1 if strict else 0.07)
    notes = _drop_shadows(notes)
    if effects:
        notes = _drop_sweep_debris(notes, effects)
    if hits:
        notes = _drop_drum_debris(notes, sorted(t for t, _kind in hits), 0.5 if strict else 0.35)
    if strict:
        notes = [n for n in notes if n[1] - n[0] >= 0.09 and not (n[3] < 0.3 and n[1] - n[0] < 0.16)]
        notes = _limit_crowd(notes, 6)
    return notes


def _join_fragments(notes, gap):
    """A note that follows one of the same pitch at once, and is short or much fainter, is its tail."""
    out = []
    last = {}                                   # pitch -> index in out
    for n in notes:
        i = last.get(n[2])
        if i is not None:
            m = out[i]
            close = n[0] - m[1] <= gap
            tail = (n[1] - n[0]) < 0.11 or n[3] < 0.5 * m[3]
            if close and tail:
                out[i] = (m[0], max(m[1], n[1]), m[2], m[3])
                continue
        last[n[2]] = len(out)
        out.append(n)
    return out


def _drop_shadows(notes):
    """A faint note a semitone beside a much stronger one that sounds through it is leakage."""
    keep = []
    for i, n in enumerate(notes):
        shadow = False
        for m in notes[max(0, i - 30):i + 30]:
            if abs(m[2] - n[2]) != 1 or m[3] < 2.5 * n[3]:
                continue
            overlap = min(m[1], n[1]) - max(m[0], n[0])
            if overlap >= 0.5 * (n[1] - n[0]):
                shadow = True
                break
        if not shadow:
            keep.append(n)
    return keep


def _drop_sweep_debris(notes, effects):
    """What an effect leaves in a transcription: a staircase along a sweep, a low note under an impact."""
    effects = [e for e in effects if e["end"] > e["start"]]
    if not effects:
        return notes
    keep = []
    for n in notes:
        debris = False
        mid, length = 0.5 * (n[0] + n[1]), n[1] - n[0]
        for e in effects:
            kind = e["kind"]
            if kind == "impact":                # the boom, read as a bass note, and the crack as a spray
                if e["start"] - 0.06 <= n[0] <= e["start"] + 0.3 and (n[2] < 45 or length < 0.2):
                    debris = True
                continue
            if not (e["start"] - 0.1 <= mid <= e["end"] + 0.1) or length > 0.45:
                continue
            if kind == "swell":
                debris = bool(e.get("noise")) and n[3] < 0.5
            else:
                along = min(1.0, max(0.0, (mid - e["start"]) / (e["end"] - e["start"])))
                where = e["low"] + (e["high"] - e["low"]) * (along if kind == "riser" else 1.0 - along)
                if e.get("noise"):
                    debris = abs(n[2] - where) <= 7 and n[3] < 0.5
                else:                           # on the path, or on its second or third partial
                    debris = min(abs(n[2] - where - k) for k in (0, 12, 19)) <= 2.5
            if debris:
                break
        if not debris:
            keep.append(n)
    return keep


def _drop_drum_debris(notes, times, faint):
    """A short, faint note that begins exactly on a drum hit is usually the drum."""
    import bisect
    keep = []
    for n in notes:
        i = bisect.bisect_left(times, n[0] - 0.04)
        on_hit = i < len(times) and times[i] <= n[0] + 0.04
        if on_hit and n[1] - n[0] < 0.16 and n[3] < faint:
            continue
        keep.append(n)
    return keep


def _limit_crowd(notes, most):
    """Where more than ``most`` notes sound together, the faintest newcomers go."""
    keep = []
    for n in sorted(notes, key=lambda x: -x[3]):
        together = sum(1 for m in keep if m[0] < n[1] and n[0] < m[1]
                       and min(m[1], n[1]) - max(m[0], n[0]) >= 0.5 * (n[1] - n[0]))
        if together < most:
            keep.append(n)
    return sorted(keep)
