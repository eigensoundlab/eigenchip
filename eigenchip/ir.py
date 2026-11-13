# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""The intermediate representation every reader produces and every arranger consumes.

``Score``        notes in beats (quarter notes), as read from the source.
``Grid``         the same notes snapped to a step grid.
``Arrangement``  a handful of monophonic voices, a chord voice and drums: what
                 a chip can actually play.
"""
from __future__ import annotations

NOTE_NAMES = ["c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b"]
_NAME_TO_PC = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}


def pitch_name(midi):
    """MIDI number -> note name with octave (60 -> 'c4')."""
    return "%s%d" % (NOTE_NAMES[midi % 12], midi // 12 - 1)


def pitch_number(name):
    """Note name -> MIDI number ('c4' -> 60, 'eb3' -> 51, 'f#5' -> 78)."""
    s = name.strip().lower()
    pc = _NAME_TO_PC[s[0]]
    i = 1
    while i < len(s) and s[i] in "#b":
        pc += 1 if s[i] == "#" else -1
        i += 1
    return 12 * (int(s[i:]) + 1) + pc


class Note:
    """One note. ``start`` and ``dur`` are beats in a Score, steps in a Grid."""
    __slots__ = ("start", "dur", "pitch", "vel", "channel", "program", "drum")

    def __init__(self, start, dur, pitch, vel=96, channel=0, program=0, drum=False):
        self.start = start
        self.dur = dur
        self.pitch = pitch
        self.vel = vel
        self.channel = channel
        self.program = program
        self.drum = drum

    @property
    def end(self):
        return self.start + self.dur

    def key(self):
        return (self.start, self.dur, self.pitch, self.vel, self.channel, self.drum)

    def __repr__(self):
        return "Note(%s+%s %s ch%d%s)" % (self.start, self.dur, pitch_name(self.pitch), self.channel,
                                          " drum" if self.drum else "")


class Score:
    def __init__(self, notes=None, tempo=120.0, meter=(4, 4), title="", names=None, info=None):
        self.notes = sorted(notes or [], key=lambda n: (n.start, n.pitch))
        self.tempo = float(tempo)
        self.meter = tuple(meter)
        self.title = title
        self.names = dict(names or {})      # channel -> track name
        self.info = dict(info or {})        # reader notes: tempo changes, format...

    @property
    def length(self):
        return max((n.end for n in self.notes), default=0.0)

    def channels(self):
        return sorted({n.channel for n in self.notes if not n.drum})


class Grid:
    """A Score snapped to ``steps_per_beat`` steps per quarter note."""

    def __init__(self, notes, steps_per_beat, tempo, meter, title="", names=None, error=0.0, info=None):
        self.notes = notes
        self.steps_per_beat = steps_per_beat
        self.tempo = tempo
        self.meter = meter
        self.title = title
        self.names = dict(names or {})
        self.error = error                  # mean distance each onset moved, in steps
        self.info = dict(info or {})

    @property
    def steps_per_bar(self):
        num, den = self.meter
        return max(1, int(round(num * self.steps_per_beat * 4.0 / den)))

    @property
    def length(self):
        return max((n.end for n in self.notes), default=0)

    @property
    def pitched(self):
        return [n for n in self.notes if not n.drum]

    @property
    def drums(self):
        return [n for n in self.notes if n.drum]

    def channels(self):
        return sorted({n.channel for n in self.pitched})


def quantize(score, steps_per_beat=4):
    """Snap a Score to the step grid. Every note keeps at least one step."""
    notes, moved = [], 0.0
    for n in score.notes:
        exact = n.start * steps_per_beat
        start = int(round(exact))
        end = max(start + 1, int(round(n.end * steps_per_beat)))
        moved += abs(exact - start)
        notes.append(Note(start, end - start, n.pitch, n.vel, n.channel, n.program, n.drum))
    notes.sort(key=lambda n: (n.start, n.pitch))
    error = moved / len(notes) if notes else 0.0
    return Grid(notes, steps_per_beat, score.tempo, score.meter, score.title, score.names, error, score.info)


class Voice:
    """A line a chip channel can play: non-overlapping events.

    An event is ``(start, dur, [pitches])``. One pitch is a note; several are a
    chord (which the target may arpeggiate).
    """

    def __init__(self, name, role, events=None, instrument=None):
        self.name = name
        self.role = role                    # lead | bass | inner | chords
        self.events = list(events or [])
        self.instrument = dict(instrument or {})

    def clean(self):
        """Sort, drop empties and clip overlaps so the events never collide."""
        out = []
        for start, dur, pitches in sorted(self.events, key=lambda e: e[0]):
            if dur <= 0 or not pitches:
                continue
            if out and out[-1][0] + out[-1][1] > start:
                prev = out[-1]
                if start - prev[0] <= 0:
                    continue
                out[-1] = (prev[0], start - prev[0], prev[2])
            out.append((start, dur, list(pitches)))
        self.events = out
        return self


class Arrangement:
    def __init__(self, voices, drums=None, name="", notes=None):
        self.voices = [v.clean() for v in voices if v.events]
        self.drums = sorted(drums or [])    # [(step, ["k", "h"]), ...]
        self.name = name                    # arranger that produced it
        self.notes = dict(notes or {})      # free-form remarks from the arranger

    def voice(self, role):
        for v in self.voices:
            if v.role == role:
                return v
        return None
