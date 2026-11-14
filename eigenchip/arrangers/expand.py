# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""expand - keep the tune, write the rest anew from the harmony.

The other arrangers *reduce*: every note they play was in the source.  This one
goes the other way.  It keeps one line - the tune - and writes a bass, a chord
voice, an inner line and (from four voices up) nothing else that was heard.

It serves two cases with one method:

* **A tune and nothing else** (one melody line: a sketch, something hummed and
  transcribed).  The chords are chosen to fit the tune: a harmonisation.
* **A dense source** (a recording of an orchestra).  The transcription of the
  inner parts is the least reliable thing in the chain and, played back, the
  most disturbing.  Here every note that was heard is only *evidence* for the
  chord of each half bar; what is played is the tune and clean parts written
  from those chords.  Less faithful, far more consonant.

Method: the key is the major scale holding most of the sound; each half bar
gets one of its seven triads, the best path through them (the notes sounding
in the half bar speak for a chord that contains them and against one that
does not; a change of chord costs a little, so harmony moves when the music
says so).  Bass: the root, struck again where the tune's rhythm is busy.
Chords: the triad around middle C, arpeggiated.  Inner: the chord tone next
below the tune.
"""
from __future__ import annotations

from ..ir import Arrangement
from . import roles
from .common import line, map_drums, voice

NAME = "expand"
SUMMARY = "Keep the tune; write bass, chords and an inner line anew from the harmony."

SCALE = (0, 2, 4, 5, 7, 9, 11)
TRIADS = [(SCALE[i], SCALE[(i + 2) % 7], SCALE[(i + 4) % 7]) for i in range(7)]     # I ii iii IV V vi vii
LIKELY = (1.0, 0.9, 0.85, 1.0, 1.0, 0.95, 0.6)      # how readily each degree is taken (the diminished one rarely)
AGAINST = 0.6           # what a note outside the chord takes away, against what a note inside it gives
CHANGE = 0.12           # cost of changing chord, as a share of a window's full weight
TUNE = 2.0              # the tune's notes weigh this much more than the others as evidence


def key_tonic(notes):
    """The tonic (0-11) of the major scale that holds most of the sound, by length and loudness."""
    weight = [0.0] * 12
    for n in notes:
        weight[n.pitch % 12] += n.dur * (0.5 + n.vel / 254.0)
    return max(range(12), key=lambda t: sum(weight[(t + s) % 12] for s in SCALE))


def chords(notes, tune, total, window, tonic):
    """One triad (as three pitch classes, root first) per window: the best path through the seven of the key."""
    lead = {id(n) for n in tune}
    count = max(1, -(-total // window))
    fit = []
    for w in range(count):
        a, b = w * window, (w + 1) * window
        heard = [0.0] * 12
        for n in notes:
            over = min(n.end, b) - max(n.start, a)
            if over > 0:
                heard[n.pitch % 12] += over * (0.5 + n.vel / 254.0) * (TUNE if id(n) in lead else 1.0)
        full = sum(heard) or 1.0
        row = []
        for degree, triad in enumerate(TRIADS):
            pcs = {(tonic + p) % 12 for p in triad}
            inside = sum(heard[pc] for pc in pcs)
            row.append(LIKELY[degree] * (inside - AGAINST * (sum(heard) - inside)) / full)
        fit.append(row if sum(heard) > 0 else None)
    best, back = [0.0] * 7, []
    for row in fit:                                         # the best path: Viterbi over the seven triads
        if row is None:
            back.append(list(range(7)))                     # silence: the chord stays what it was
            continue
        came = [max(range(7), key=lambda j: best[j] - (CHANGE if j != i else 0.0)) for i in range(7)]
        best = [best[came[i]] - (CHANGE if came[i] != i else 0.0) + row[i] for i in range(7)]
        back.append(came)
    at = max(range(7), key=best.__getitem__)
    path = []
    for came in reversed(back):
        path.append(at)
        at = came[at]
    path.reverse()
    return [tuple((tonic + p) % 12 for p in TRIADS[d]) for d in path]


def _place(pc, low):
    """The pitch of class ``pc`` at or above ``low``."""
    return low + (pc - low) % 12


def arrange(grid, voices=4):
    notes = grid.pitched
    if not notes:
        return Arrangement([], map_drums(grid.drums), NAME, {})
    parts = roles._split(grid)
    if parts is None:                                       # one line: it is the tune
        tune_events, used = line(notes, top=True)
        remarks = {"tune": "the only line"}
    else:
        tune_events, _bass, _rest, remarks = parts
        used = [n for n in notes if n.channel == remarks.get("lead_channel")]
    total = grid.length
    window = max(1, grid.steps_per_bar // 2)
    tonic = key_tonic(notes)
    path = chords(notes, used, total, window, tonic)
    remarks.update(tonic=tonic, chords=len({c for c in path}), written="bass, chords and inner line are new")

    def runs():
        """(start, steps, chord) with the same chord in neighbouring windows put together, bar by bar."""
        out = []
        for w, chord in enumerate(path):
            start = w * window
            if out and out[-1][2] == chord and start % grid.steps_per_bar != 0:
                out[-1] = (out[-1][0], out[-1][1] + window, chord)
            else:
                out.append((start, min(window, total - start), chord))
        return [r for r in out if r[1] > 0]

    busy = len(tune_events) / max(1.0, total / float(grid.steps_per_beat)) >= 0.75      # tune notes per beat
    bass, harmony = [], []
    for start, steps, chord in runs():
        root = _place(chord[0], 36)                         # C2 and up
        if busy and steps >= window:                        # a moving tune: the bass marks every half bar
            for s in range(start, start + steps, window):
                fifth = s != start and (s // window) % 2 == 1
                bass.append((s, min(window, start + steps - s), [_place(chord[2], 36) if fifth else root]))
        else:
            bass.append((start, steps, [root]))
        harmony.append((start, steps, sorted(_place(pc, 55) for pc in chord)))          # around middle C
    inner = []
    for start, steps, pitches in tune_events:               # the chord tone next below the tune, a third or more away
        chord = path[min(len(path) - 1, start // window)]
        under = max((p for p in (_place(pc, pitches[0] - 12) for pc in chord) if p <= pitches[0] - 3),
                    default=None)
        if under is not None and under >= 48:
            inner.append((start, steps, [under]))
    out = [voice("lead", tune_events)]
    if voices >= 2:
        out.append(voice("bass", bass))
    if voices >= 3:
        out.append(voice("chords", harmony))
    if voices >= 4 and inner:
        out.insert(2, voice("inner", inner))
    return Arrangement(out, map_drums(grid.drums), NAME, remarks)
