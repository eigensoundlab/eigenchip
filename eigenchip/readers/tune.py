# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""A tune written out by hand, in the track notation of CLIo's songs.

    e4 e4 f4 g4 | g4 f4 e4 d4 | c4 c4 d4 e4 | e4:3 d4 d4:4

A token is a note (``c4``, ``f#4``, ``eb3``) of one beat, or with its length in
beats after a colon (``c4:2``, ``g4:.5``, ``a4:1.5``); ``.`` or ``r`` is a rest,
``-`` holds the note before, ``|`` is a bar line and means nothing.  Lengths
count **beats** here, not steps as in a song: a tune is thought in beats.
``[c4 e4]`` sounds together; ``c4@6`` is played softer (levels 0 to 9).

A double bar line ``||`` begins a new **part**.  Parts are called A, B, C... in
the order they are written, each begins on a bar line, and a *form* such as
``A A B A`` says in which order they are played (``play_form``) - and, with
marks, how: ``(A)`` without the tune, ``A-`` quiet, ``A+`` a tone higher
(``eigenchip/arrangers/plan.py``).
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
    bar = bar_beats(meter)
    parts = [0.0]
    for token in _TOKEN.findall(text or ""):
        if token == "|":
            continue
        if token == "||":                                   # a new part, from the next bar line on
            at, last = -(-at // bar) * bar if at % bar > 1e-9 else at, None
            if at > parts[-1]:
                parts.append(at)
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
    return Score(notes, float(tempo), tuple(meter), title, {0: "tune"}, {"sections": parts})


def bar_beats(meter):
    return meter[0] * 4.0 / meter[1]


def read_notes(notes, tempo=100.0, meter=(4, 4), title="A tune", sections=None):
    """The Score of a tune given as ``(start, length, pitch)`` in beats: what a piano roll or a keyboard hands over.
    ``sections`` are the bars (counted from 0) at which a new part begins."""
    out = []
    for start, length, pitch in notes or []:
        start, length, pitch = float(start), float(length), int(pitch)
        if start < 0 or length <= 0 or not 12 <= pitch <= 119:
            raise ValueError("A note of the tune is out of range (start %s, length %s, pitch %s)." % (start, length, pitch))
        out.append(Note(start, length, pitch, 100, 0, 0))
    if not out:
        raise ValueError("There are no notes in the tune yet.")
    out.sort(key=lambda n: (n.start, n.pitch))
    starts = sorted({0.0} | {int(b) * bar_beats(meter) for b in sections or [] if int(b) > 0})
    return Score(out, float(tempo), tuple(meter), title, {0: "tune"}, {"sections": starts})


def parts_of(score):
    """The parts of a tune as ``[(name, start, beats)]``: A, B, C... from one double bar line to the next."""
    bar = bar_beats(score.meter)
    end = max(bar, -(-max(n.end for n in score.notes) // bar) * bar)
    starts = sorted({0.0} | {float(s) for s in score.info.get("sections") or [] if 0 < s < end})
    if len(starts) > 26:
        raise ValueError("A tune has at most 26 parts, A to Z.")
    return [(chr(65 + i), a, b - a) for i, (a, b) in enumerate(zip(starts, starts[1:] + [end]))]


def parse_form(text, names):
    """'A A B A' or 'aaba' -> ['A', 'A', 'B', 'A']; nothing -> every part once, in order.  The marks that say how a
    part is played - (A), A-, A+ - are read by ``arrangers.plan.parse``; here only the letters are returned."""
    from ..arrangers import plan
    return [name for name, _how in plan.parse(text, list(names))]


def play_form(score, form=None):
    """The tune as it is played: its parts in the order of the form.

    Returns a new Score.  Its ``info`` holds ``parts`` - ``[name, start in the song, start as written, beats]`` for
    each part played, all in beats - ``phrase_starts``, where each of them begins, ``plan`` - how each is played
    (``arrangers.plan``: without the tune, quiet, a tone higher) - and ``longer``, a long version of the form.
    """
    from ..arrangers import plan
    parts = parts_of(score)
    by_name = {name: (start, beats) for name, start, beats in parts}
    how = plan.parse(form, [name for name, _s, _b in parts])
    order = [name for name, _how in how]
    notes, played, at = [], [], 0.0
    for name in order:
        start, beats = by_name[name]
        for n in score.notes:
            if start <= n.start < start + beats:
                notes.append(Note(at + n.start - start, min(n.dur, start + beats - n.start), n.pitch, n.vel,
                                  n.channel, n.program, n.drum))
        played.append([name, at, start, beats])
        at += beats
    if not notes:
        raise ValueError("The parts in the form have no notes in them.")
    info = dict(score.info, parts=played, phrase_starts=[p[1] for p in played], form=plan.write(how),
                plan=[flags for _name, flags in how], longer=plan.write(plan.longer(how)),
                sections=[start for _n, start, _b in parts])
    return Score(notes, score.tempo, score.meter, score.title, dict(score.names), info)


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
    bar = bar_beats(score.meter)
    breaks = sorted(float(s) for s in score.info.get("sections") or [] if s > 0)
    tokens, at = [], 0.0

    def put(text, length):
        nonlocal at
        tokens.append(text + _beats(length))
        at += length
        if any(abs(at - b) < 1e-6 for b in breaks):
            tokens.append("||")
        elif abs(at / bar - round(at / bar)) < 1e-6:
            tokens.append("|")

    for i, start in enumerate(starts):
        for b in [b for b in breaks if at + 1e-6 < b <= start + 1e-6]:      # rest up to where the next part begins
            put(".", b - at)
        if start - at >= 0.25:
            put(".", start - at)
        until = starts[i + 1] if i + 1 < len(starts) else None
        length = max(n.dur for n in groups[start])
        length = max(0.25, round((min(length, until - start) if until is not None else length) * 4) / 4.0)
        names = [pitch_name(n.pitch).lower() for n in sorted(groups[start], key=lambda n: n.pitch)]
        put(names[0] if len(names) == 1 else "[%s]" % " ".join(names), length)
    return " ".join(tokens).rstrip(" |")
