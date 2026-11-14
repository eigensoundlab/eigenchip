# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Which of the notes are the tune?

Sorting notes into lines one onset at a time (``eigenchip/voices.py``) has no
memory: every note goes to the nearest line of that moment, and a tune in long
notes among busier parts is torn apart.  Here the tune is chosen with the whole
piece in view, as the one line through the transcribed notes that carries the
most *prominent* sound for the least leaping:

* A note counts by how long it sounds and by its **standing** among the notes
  that sound with it - how strong its pitch is in the sound, against the
  strongest of them.  The tune is usually what one hears first, wherever it
  lies: under a high figure, between held chords.
* Among notes of like standing the higher one gets a little more (the top of a
  chord is its tune), a move by step is rewarded (a tune walks), a leap costs,
  a far leap costs much more, and waiting costs a little.

The best such line is found exactly, by dynamic programming over the notes in
order of onset.  It is a line of *notes that were heard*: a tune the
transcriber missed cannot be chosen.
"""
from __future__ import annotations

from .transcribe import LOW, _salience

LOWEST = 43             # below G2 a line is a bass, not a tune
GAMMA = 3.0             # how steeply standing falls off below the most prominent note
TOP = 0.15              # bonus for a note with nothing above it when it starts
STEP = 0.15             # bonus for moving by a semitone or a tone, in seconds of full sound
LEAP = 0.015            # cost per semitone moved
FAR = 0.03              # further cost per semitone beyond a fifth
WAIT = 0.02             # cost per second of silence within the line
REACH = 6.0             # seconds: how far back a note looks for the one before it


def standing(spec, notes, gamma=GAMMA, lowest=LOWEST):
    """For each ``(start, end, pitch, strength)`` note, 0..1: its prominence against the notes sounding with it.

    Only notes from ``lowest`` up take part; the others stand at 0.
    """
    np = spec.np
    sal = _salience(spec)[2]
    frames, width = sal.shape
    spans = []
    for start, end, pitch, _strength in notes:
        a = min(frames - 1, max(0, int(start * spec.fps)))
        spans.append((a, min(frames, max(a + 1, int(end * spec.fps))), pitch - LOW))
    best = np.full(frames, 1e-9)
    for (a, b, col), note in zip(spans, notes):
        if note[2] >= lowest and 0 <= col < width:
            best[a:b] = np.maximum(best[a:b], sal[a:b, col])
    out = []
    for (a, b, col), note in zip(spans, notes):
        ok = note[2] >= lowest and 0 <= col < width
        out.append(float(((sal[a:b, col] / best[a:b]) ** gamma).mean()) if ok else 0.0)
    return out


def tune(notes, weights, lowest=LOWEST, top=TOP, step=STEP, leap=LEAP, far=FAR, wait=WAIT, reach=REACH, overlap=0.06):
    """Indices into ``notes`` of the line that carries the most prominent sound for the least leaping."""
    order = sorted((i for i, n in enumerate(notes) if n[2] >= lowest), key=lambda i: (notes[i][0], -notes[i][2]))
    if not order:
        return []
    ns = [notes[i] for i in order]
    worth = []
    for k, n in enumerate(ns):
        covered = any(m[2] > n[2] and m[0] <= n[0] + 0.03 and m[1] > n[0] + 0.05 for m in ns)
        worth.append((n[1] - n[0]) * weights[order[k]] * (1.0 if covered else 1.0 + top))
    best = list(worth)
    before = [-1] * len(ns)
    for i, n in enumerate(ns):
        for j in range(i - 1, -1, -1):
            m = ns[j]
            if n[0] - m[1] > reach:
                if n[0] - m[0] > reach + 30.0:
                    break                                   # nothing that old can still be sounding
                continue
            if m[1] > n[0] + overlap:
                continue                                    # still sounding: one line plays one note at a time
            move = abs(n[2] - m[2])
            cost = leap * min(move, 12) + wait * max(0.0, n[0] - m[1])
            if move > 7:
                cost += far * (min(move, 19) - 7)
            elif 1 <= move <= 2 and n[0] - m[1] < 0.5:
                cost -= step
            if best[j] - cost + worth[i] > best[i]:
                best[i] = best[j] - cost + worth[i]
                before[i] = j
    i = max(range(len(ns)), key=best.__getitem__)
    out = []
    while i >= 0:
        out.append(order[i])
        i = before[i]
    return out[::-1]


def find(spec, notes):
    """Indices of the notes that make the tune (empty when there are too few notes to speak of one)."""
    if len(notes) < 4:
        return []
    return tune(notes, standing(spec, notes))

