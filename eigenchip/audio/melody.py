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
OFF_KEY = 0.5           # what a note outside the key of the piece is worth, against one inside it
IN_KEY = 0.85           # share of the sound that must lie in one scale for the piece to have a key at all
MEMORY = 8.0            # seconds to either side over which the tune remembers where it lies
NEAR = 7                # semitones from there that cost nothing
AWAY = 0.1              # what each further semitone takes off a note's worth
BLIP = 0.1              # seconds: a shorter note is not a note of the tune
JOIN = 0.3              # seconds: two pieces of one pitch closer than this may be one note that was cut
SCALE = (0, 2, 4, 5, 7, 9, 11)


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


def key_of(notes):
    """The scale the piece lies in, as a set of pitch classes - or None when it lies in none.

    Seven notes of a major scale (a minor key shares its relative major's), chosen by how much of the sound, by
    length and strength, they hold. A piece that keeps to no scale is not corrected towards one.
    """
    weight = [0.0] * 12
    for start, end, pitch, strength in notes:
        weight[pitch % 12] += (end - start) * strength
    total = sum(weight)
    if total <= 0:
        return None
    share, tonic = max((sum(weight[(t + s) % 12] for s in SCALE) / total, t) for t in range(12))
    return {(tonic + s) % 12 for s in SCALE} if share >= IN_KEY else None


def _register(notes, chosen, weights, memory=MEMORY):
    """For every note, where the tune lies around that time: the middle of its notes, weighed by their worth."""
    if not chosen:
        return [None] * len(notes)
    line = [(0.5 * (notes[i][0] + notes[i][1]), notes[i][2], (notes[i][1] - notes[i][0]) * weights[i]) for i in chosen]
    out = []
    for start, end, _pitch, _strength in notes:
        at = 0.5 * (start + end)
        near = sorted((p, w) for t, p, w in line if abs(t - at) <= memory and w > 0)
        if not near:
            near = sorted((p, w) for t, p, w in line if w > 0) or [(notes[chosen[0]][2], 1.0)]
        half, run = 0.5 * sum(w for _p, w in near), 0.0
        for p, w in near:                                   # weighted median
            run += w
            if run >= half:
                out.append(p)
                break
    return out


def find(spec, notes):
    """Indices of the notes that make the tune (empty when there are too few notes to speak of one).

    Three things are known only once a first line has been drawn, so the search runs twice: the key of the piece
    (a note outside it is worth less: more often a mistake of the ear than a chromatic step), where the tune lies
    (a note far from there is something else filling a rest), and that a blip is not a note of the tune.
    """
    if len(notes) < 4:
        return []
    weights = standing(spec, notes)
    key = key_of(notes)
    if key:
        weights = [w if n[2] % 12 in key else w * OFF_KEY for w, n in zip(weights, notes)]
    weights = [w if n[1] - n[0] >= BLIP else 0.0 for w, n in zip(weights, notes)]
    chosen = tune(notes, weights)
    for _again in range(2):                                 # where the tune lies settles in a pass or two
        lies = _register(notes, chosen, weights)
        near = [w if c is None else w * max(0.2, 1.0 - AWAY * max(0, abs(n[2] - c) - NEAR))
                for w, n, c in zip(weights, notes, lies)]
        again = tune(notes, near)
        if again == chosen:
            break
        chosen = again
    return [i for i in chosen if weights[i] > 0]


def struck_again(spec, pitch, at):
    """Was this pitch struck anew at time ``at`` - or is it one note that went on sounding?

    The same test the note cutter uses inside a held note: the pitch's own level, in the short window, has a
    notch just before ``at`` and is clearly louder after it.
    """
    energy = spec.energy
    col = pitch - LOW
    if not 0 <= col < energy.shape[1]:
        return True
    e = energy[:, col]
    frame = int(round(at * spec.flux_fps))
    after = e[frame + 2:frame + 7]
    prior = e[max(0, frame - 12):max(1, frame - 4)]
    if not len(after) or not len(prior):
        return True
    dip = float(e[max(0, frame - 3):frame + 1].mean())
    after, prior = float(after.mean()), float(prior.mean())
    return after > 1.4 * dip and (dip < 0.72 * prior or after > 1.8 * prior)


def mend(spec, notes, chosen, join=JOIN):
    """The tune as notes, with the pieces of a held note put together again.

    A long note in a real recording wavers, and the transcriber writes it as several: played back, it stutters.
    Two neighbours of one pitch, close together, are one note unless the pitch was heard to be struck again.
    """
    out = []
    for i in chosen:
        start, end, pitch, strength = notes[i]
        if out and out[-1][2] == pitch and start - out[-1][1] <= join and not struck_again(spec, pitch, start):
            out[-1] = (out[-1][0], max(end, out[-1][1]), pitch, max(strength, out[-1][3]))
        else:
            out.append((start, end, pitch, strength))
    return out

