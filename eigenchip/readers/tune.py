# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""A tune written out by hand, in the track notation of CLIo's songs.

    e4 e4 f4 g4 | g4 f4 e4 d4 | c4 c4 d4 e4 | e4:3 d4 d4:4

A token is a note (``c4``, ``f#4``, ``eb3``) of one beat, or with its length in
beats after a colon (``c4:2``, ``g4:.5``, ``a4:1.5``); ``.`` or ``r`` is a rest,
``-`` holds the note before, ``|`` is a bar line and means nothing.  Lengths
count **beats** here, not steps as in a song: a tune is thought in beats.
``[c4 e4]`` sounds together; ``c4@6`` is played softer (levels 0 to 9).
"""
from __future__ import annotations

import re

from ..ir import Note, Score, pitch_number

_TOKEN = re.compile(r"\[[^\]]*\]\S*|\S+")
_NOTE = re.compile(r"^[a-g][#b]*-?\d$")
SHORTEST = 0.25             # beats: a sixteenth


def read_tune(text, tempo=100.0, meter=(4, 4), title="A tune"):
    """The Score of a tune written as text.  Raises ``ValueError`` naming the token it cannot read."""
    notes, at, last = [], 0.0, None
    for token in _TOKEN.findall(text or ""):
        if token == "|":
            continue
        body, _colon, length = token.partition(":") if not token.startswith("[") else (
            token[:token.index("]") + 1], ":", token[token.index("]") + 1:].lstrip(":").partition(":")[0])
        if token.startswith("["):
            rest = token[token.index("]") + 1:]
            level = re.search(r"@(\d)", rest)
            length = rest.partition(":")[2]
        else:
            level = re.search(r"@(\d)", body)
            body = re.split(r"[@>]", body)[0]
        try:
            beats = float(length) if length else 1.0
        except ValueError:
            raise ValueError("'%s': the length after the colon is not a number of beats." % token)
        if not SHORTEST <= beats <= 64:
            raise ValueError("'%s': a length is between a quarter of a beat and 64 beats." % token)
        if body in (".", "r"):
            at, last = at + beats, None
            continue
        if body == "-":
            if last is None:
                raise ValueError("'-' holds the note before it, and there is none.")
            for n in last:
                n.dur += beats
            at += beats
            continue
        names = body[1:-1].split() if body.startswith("[") else [body]
        if not names or any(not _NOTE.match(name.lower()) for name in names):
            raise ValueError("'%s' is not a note. Write notes as c4, f#4 or eb3; a rest as a dot." % token)
        vel = 100 if not level else 30 + 10 * int(level.group(1))
        last = [Note(at, beats, pitch_number(name), vel, 0, 0) for name in names]
        if any(not 12 <= n.pitch <= 119 for n in last):
            raise ValueError("'%s' is outside the range of the instruments." % token)
        notes += last
        at += beats
    if not notes:
        raise ValueError("There are no notes in the tune yet.")
    return Score(notes, float(tempo), tuple(meter), title, {0: "tune"})


def read_notes(notes, tempo=100.0, meter=(4, 4), title="A tune"):
    """The Score of a tune given as ``(start, length, pitch)`` in beats: what a piano roll or a keyboard hands over."""
    out = []
    for start, length, pitch in notes or []:
        start, length, pitch = float(start), float(length), int(pitch)
        if start < 0 or length <= 0 or not 12 <= pitch <= 119:
            raise ValueError("A note of the tune is out of range (start %s, length %s, pitch %s)." % (start, length, pitch))
        out.append(Note(start, length, pitch, 100, 0, 0))
    if not out:
        raise ValueError("There are no notes in the tune yet.")
    out.sort(key=lambda n: (n.start, n.pitch))
    return Score(out, float(tempo), tuple(meter), title, {0: "tune"})


def _beats(length):
    text = ("%.4f" % length).rstrip("0").rstrip(".")
    return "" if text == "1" else ":" + (text[1:] if text.startswith("0.") else text)


def write_tune(score):
    """A score as tune text, so that what was drawn on the roll can be read and kept. The inverse of ``read_tune``
    for one line; notes that start together are written together, a note still sounding when the next starts is
    cut there (text holds one line)."""
    from ..ir import pitch_name
    groups = {}
    for n in score.notes:
        if not n.drum:
            groups.setdefault(round(n.start * 4) / 4.0, []).append(n)
    starts = sorted(groups)
    bar = score.meter[0] * 4.0 / score.meter[1]
    tokens, at = [], 0.0

    def put(text, length):
        nonlocal at
        tokens.append(text + _beats(length))
        at += length
        if abs(at / bar - round(at / bar)) < 1e-6:
            tokens.append("|")

    for i, start in enumerate(starts):
        if start - at >= 0.25:
            put(".", start - at)
        until = starts[i + 1] if i + 1 < len(starts) else None
        length = max(n.dur for n in groups[start])
        length = max(0.25, round((min(length, until - start) if until is not None else length) * 4) / 4.0)
        names = [pitch_name(n.pitch).lower() for n in sorted(groups[start], key=lambda n: n.pitch)]
        put(names[0] if len(names) == 1 else "[%s]" % " ".join(names), length)
    return " ".join(tokens).rstrip(" |")
