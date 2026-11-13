# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""How much of the original survived the reduction?

All measures are symbolic: they compare the notes of the source grid with the
notes of the arrangement, step by step. Nothing is listened to, so these say
"the right pitches are there at the right time", not "it sounds good".

melody_recall    share of the true melody's notes that the lead voice plays
                 (same step, same pitch). Needs to be told the melody channel.
bass_recall      share of the true bass notes found in the bass voice
                 (same step, same pitch class).
pitch_recall     share of the source's sounding (step, pitch class) pairs that
                 also sound in the arrangement: how much was kept.
pitch_precision  share of the arrangement's (step, pitch class) pairs that
                 sound in the source: how little was invented.
chroma           mean cosine similarity, beat by beat, of the 12 pitch-class
                 profiles: is the harmony the same?
onset_f1         agreement on *when* notes start.
drum_recall      share of drum hits kept.
compression      unique patterns / patterns: lower means more repetition found.
"""
from __future__ import annotations

import math

from .arrangers.common import map_drums


def _sounding(notes):
    """{step: set(pitch classes)} for (start, dur, pitch) triples."""
    out = {}
    for start, dur, pitch in notes:
        for t in range(start, start + dur):
            out.setdefault(t, set()).add(pitch % 12)
    return out


def _arr_notes(arrangement):
    out = []
    for v in arrangement.voices:
        for start, dur, pitches in v.events:
            for p in pitches:
                out.append((start, dur, p))
    return out


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def _profile(notes, start, end):
    vec = [0.0] * 12
    for s, d, p in notes:
        overlap = min(s + d, end) - max(s, start)
        if overlap > 0:
            vec[p % 12] += overlap
    return vec


def evaluate(grid, arrangement, song=None, truth=None):
    """Return a dict of scores (None where a measure does not apply)."""
    truth = truth or {}
    src = [(n.start, n.dur, n.pitch) for n in grid.pitched]
    out = _arr_notes(arrangement)
    result = {}

    lead = arrangement.voice("lead")
    mel_ch = truth.get("melody")
    if mel_ch is not None and lead is not None:
        want = [(n.start, n.pitch) for n in grid.pitched if n.channel == mel_ch]
        have = {(s, p) for s, _d, ps in lead.events for p in ps}
        result["melody_recall"] = sum(1 for w in want if w in have) / float(len(want) or 1)
    else:
        result["melody_recall"] = None

    bass = arrangement.voice("bass")
    bass_ch = truth.get("bass")
    if bass_ch is not None and bass is not None:
        want = [(n.start, n.pitch % 12) for n in grid.pitched if n.channel == bass_ch]
        have = {(s, p % 12) for s, _d, ps in bass.events for p in ps}
        result["bass_recall"] = sum(1 for w in want if w in have) / float(len(want) or 1)
    else:
        result["bass_recall"] = None

    a, b = _sounding(src), _sounding(out)
    src_pairs = sum(len(v) for v in a.values())
    out_pairs = sum(len(v) for v in b.values())
    both = sum(len(a[t] & b.get(t, set())) for t in a)
    result["pitch_recall"] = both / float(src_pairs or 1)
    result["pitch_precision"] = both / float(out_pairs or 1)

    spb = grid.steps_per_beat
    sims = []
    for start in range(0, grid.length, spb):
        pa = _profile(src, start, start + spb)
        if any(pa):
            sims.append(_cosine(pa, _profile(out, start, start + spb)))
    result["chroma"] = sum(sims) / float(len(sims) or 1)

    on_a = {s for s, _d, _p in src}
    on_b = {s for s, _d, _p in out}
    hit = len(on_a & on_b)
    prec, rec = hit / float(len(on_b) or 1), hit / float(len(on_a) or 1)
    result["onset_f1"] = 2 * prec * rec / (prec + rec) if prec + rec else 0.0

    src_drums = {(s, h) for s, hits in map_drums(grid.drums) for h in hits}
    if src_drums:
        got = {(s, h) for s, hits in arrangement.drums for h in hits}
        result["drum_recall"] = len(src_drums & got) / float(len(src_drums))
    else:
        result["drum_recall"] = None

    if song:
        seq = song.get("sequence", [])
        result["compression"] = len(set(seq)) / float(len(seq) or 1)
    else:
        result["compression"] = None
    result["voices"] = len(arrangement.voices)
    return result


COLUMNS = ["melody_recall", "bass_recall", "pitch_recall", "pitch_precision", "chroma", "onset_f1",
           "compression"]


def polyphony(grid):
    """(mean, max) number of pitched notes sounding at once."""
    count = {}
    for n in grid.pitched:
        for t in range(n.start, n.end):
            count[t] = count.get(t, 0) + 1
    if not count:
        return 0.0, 0
    return sum(count.values()) / float(len(count)), max(count.values())
