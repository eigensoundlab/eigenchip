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
