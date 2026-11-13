# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Splitting one heap of notes into lines.

A MIDI file says which instrument plays each note.  A transcription does not:
it is one piano roll.  Arrangers that look for "the melody channel" then have
nothing to choose between.  ``separate`` gives the notes channels again, by
the oldest rule of counterpoint: a line moves by small steps and does not jump
over its neighbours.

Notes are taken in order of onset (highest first within a chord).  Each goes
to the line whose last note is nearest in pitch, among the lines that are free
at that moment; a long silence in a line makes it a less likely home, and a
leap of more than ``max_leap`` semitones opens a new line while there is room.
When every line is busy the note joins the nearest one as a chord note.

This is a greedy baseline (after the "nearest neighbour" streaming of Chew and
Wu).  It cannot follow voices that cross, and it has no idea of timbre.
"""
from __future__ import annotations

from .ir import Note, Score


def separate(score, max_voices=5, max_leap=9.0, rest_cost=1.5, overlap=0.1):
    """Return a copy of ``score`` whose pitched notes are spread over up to ``max_voices`` channels.

    Channels are numbered from the top line down (0 is the highest on average).
    Drum notes keep their channel.
    """
    pitched = sorted((n for n in score.notes if not n.drum), key=lambda n: (round(n.start, 4), -n.pitch))
    drums = [n for n in score.notes if n.drum]
    lines = []                                  # each: {"notes": [...], "pitch": last pitch, "end": when it is free}
    for n in pitched:
        best, best_cost = None, None
        for line in lines:
            if line["end"] > n.start + overlap:
                continue                        # still sounding
            cost = abs(n.pitch - line["pitch"]) + rest_cost * min(4.0, max(0.0, n.start - line["end"]))
            if best is None or cost < best_cost:
                best, best_cost = line, cost
        if best is not None and (best_cost <= max_leap or len(lines) >= max_voices):
            pass
        elif len(lines) < max_voices:
            best = {"notes": [], "pitch": n.pitch, "end": 0.0}
            lines.append(best)
        elif best is None:                      # every line is busy: a chord note of the nearest one
            best = min(lines, key=lambda line: abs(n.pitch - line["pitch"]))
        best["notes"].append(n)
        best["pitch"] = n.pitch
        best["end"] = max(best["end"], n.end)
    lines.sort(key=lambda line: -sum(m.pitch for m in line["notes"]) / float(len(line["notes"])))
    out = []
    for channel, line in enumerate(lines):
        for m in line["notes"]:
            out.append(Note(m.start, m.dur, m.pitch, m.vel, channel, m.program))
    names = {i: "voice %d" % (i + 1) for i in range(len(lines))}
    info = dict(score.info)
    info["lines_guessed"] = True                # arrangers may trust these channels less than real ones
    return Score(out + drums, score.tempo, score.meter, score.title, names, info)


def flatten(score):
    """All pitched notes on one channel: what a transcription looks like."""
    notes = [Note(n.start, n.dur, n.pitch, n.vel, n.channel if n.drum else 0, 0, n.drum) for n in score.notes]
    return Score(notes, score.tempo, score.meter, score.title, {0: "all"}, score.info)


def consistency(truth, guess):
    """How well do two ways of dividing the same notes into lines agree?  0..1.

    For every pair of notes that follow each other in a true line: are they
    also in one line of the guess?  (Average voice consistency, in spirit.)
    ``truth`` and ``guess`` are Scores holding the same notes.
    """
    where = {}
    for n in guess.notes:
        if not n.drum:
            where.setdefault((round(n.start, 4), n.pitch), []).append(n.channel)
    by_channel = {}
    for n in truth.notes:
        if not n.drum:
            by_channel.setdefault(n.channel, []).append(n)
    same = total = 0
    for notes in by_channel.values():
        notes.sort(key=lambda n: (n.start, n.pitch))
        for a, b in zip(notes, notes[1:]):
            if b.start < a.end - 1e-6:
                continue                        # a chord inside the line: not a succession
            ca = where.get((round(a.start, 4), a.pitch))
            cb = where.get((round(b.start, 4), b.pitch))
            if ca and cb:
                total += 1
                same += 1 if set(ca) & set(cb) else 0
    return same / float(total) if total else 1.0
