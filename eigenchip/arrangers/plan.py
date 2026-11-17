# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""How each part of a form is played: a short tune made longer by arrangement.

A form says in which order the parts of a tune are played - ``A A B A``.  A
mark on a part says *how*:

``(A)``   without the tune: the other voices alone - an introduction, a vamp
``A-``    quiet: without bass and drums (and without kettledrums or steam) - a breakdown
``A+``    a tone higher: everything that has a pitch moves up two semitones - a lift

Marks combine: ``(A)-`` is the chords alone.  ``longer`` makes a long version of
a form by itself: the first part without its tune to begin, the form, a quiet
part, and the first part once more and then a tone higher::

    A A B A   ->   (A) A A B A B- A A+

The parts are arranged whole first - the tune is still what the chords are
chosen from - and then thinned and moved (``apply``).  The chords shown are
those before a lift.
"""
from __future__ import annotations

import re

LIFT = 2                                                    # semitones: a whole tone up
_PART = re.compile(r"(\()?\s*([A-Za-z])\s*(\))?\s*([+-]*)")
QUIET_TRACKS = ("timpani", "steam")                         # besides bass and drums, what a quiet part leaves out


def parse(text, names):
    """'(A) A B- A+' -> ``[("A", "t"), ("A", ""), ("B", "q"), ("A", "l")]``; nothing -> every part once, plainly.

    The flags: ``t`` the tune is silent, ``q`` quiet, ``l`` lifted.  Letters may be written without spaces."""
    text = (text or "").strip()
    out, at = [], 0
    for found in _PART.finditer(text):
        if text[at:found.start()].strip(" ,|"):
            break
        opened, letter, closed, signs = found.groups()
        if bool(opened) != bool(closed):
            raise ValueError("A part without its tune is written in brackets, both of them: (A).")
        letter = letter.upper()
        if letter not in names:
            have = names[0] if len(names) == 1 else "%s to %s" % (names[0], names[-1])
            raise ValueError("The form names a part %s, and the tune has only %s. A new part begins at a double bar "
                             "line, ||, in the text - or where you double-click a bar number on the roll." % (letter, have))
        out.append((letter, ("t" if opened else "") + ("q" if "-" in signs else "") + ("l" if "+" in signs else "")))
        at = found.end()
    if text[at:].strip(" ,|"):
        raise ValueError("The form is written with the letters of the parts, for example: A A B A. "
                         "(A) is a part without its tune, A- a quiet one, A+ one a tone higher.")
    if len(out) > 64:
        raise ValueError("A form has at most 64 parts.")
    return out or [(name, "") for name in names]


def write(plan):
    """``[("A", "t"), ("B", "q")]`` -> '(A) B-'."""
    return " ".join(("(%s)" % name if "t" in how else name) + ("-" if "q" in how else "") + ("+" if "l" in how else "")
                    for name, how in plan)


def longer(plan):
    """A long version of a form that is played plainly; a form that has marks already is left as it is."""
    if not plan or any(how for _name, how in plan):
        return list(plan)
    first = plan[0][0]
    other = next((name for name, _how in reversed(plan) if name != first), first)
    return [(first, "t")] + list(plan) + [(other, "q"), (first, ""), (first, "l")]


def _split(events, a, b):
    """``(outside, inside)``: the events cut at ``a`` and ``b`` (steps); ``b`` may be None for 'to the end'."""
    outside, inside = [], []
    for event in events:
        start, steps = event[0], event[1]
        end = start + steps
        last = end if b is None else min(end, b)
        if last <= a or start >= last:                      # wholly outside
            outside.append(event)
            continue
        if start < a:
            outside.append((start, a - start) + tuple(event[2:]))
        inside.append((max(start, a), last - max(start, a)) + tuple(event[2:]))
        if last < end:
            outside.append((last, end - last) + tuple(event[2:]))
    return outside, inside


def apply(arrangement, parts, flags, steps_per_beat):
    """Thin and move an arrangement, part by part.  ``parts``: ``[name, start, start as written, beats]`` for each
    part played, in beats (``readers.tune.play_form``); ``flags`` one string for each.  The last part lasts to the
    end of the piece, so a closing bar after a lifted part is lifted with it."""
    spans = [(int(round(at * steps_per_beat)), int(round((at + beats) * steps_per_beat)), how)
             for (_name, at, _written, beats), how in zip(parts, flags)]
    for i, (a, b, how) in enumerate(spans):
        if not how:
            continue
        b = None if i == len(spans) - 1 else b
        for v in arrangement.voices:
            outside, inside = _split(v.events, a, b)
            if ("t" in how and v.role in ("lead", "inner")) or ("q" in how and v.role == "bass"):
                inside = []
            elif "l" in how:
                inside = [(s, d, [p + LIFT for p in pitches]) for s, d, pitches in inside]
            v.events = sorted(outside + inside)
        for name, (events, sound) in list(arrangement.tracks.items()):
            outside, inside = _split(events, a, b)
            if "q" in how and name in QUIET_TRACKS:
                inside = []
            elif "l" in how and sound.get("wave") != "noise":
                inside = [(s, d, [p + LIFT for p in pitches]) + tuple(rest) for s, d, pitches, *rest in inside]
            arrangement.tracks[name] = (sorted(outside + inside, key=lambda e: e[0]), sound)
        if "q" in how:
            arrangement.drums = [(s, hits) for s, hits in arrangement.drums if not (a <= s and (b is None or s < b))]
    arrangement.voices = [v for v in arrangement.voices if v.events]
    return arrangement
