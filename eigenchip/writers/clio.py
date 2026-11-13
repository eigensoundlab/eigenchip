# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Write an Arrangement as a CLIo song (https://github.com/eryxgames/CLIo).

A CLIo song is JSON: instruments, named patterns holding one text track per
voice, and a sequence of pattern names. Track notation: ``c4:4`` is a note four
steps long, ``.:2`` a rest, ``-:4`` holds the previous note, ``[c4 e4 g4]:8`` a
chord, ``|`` a bar line (ignored by the player).

The piece is cut into patterns of a few bars and identical patterns are stored
once, which is both how trackers work and a useful measure of how much
repetition the arranger preserved.
"""
from __future__ import annotations

import json

from ..arrangers.common import INSTRUMENTS
from ..ir import pitch_name


def _token(pitches, length):
    body = pitch_name(pitches[0]) if len(pitches) == 1 else "[%s]" % " ".join(pitch_name(p) for p in pitches)
    return body if length == 1 else "%s:%d" % (body, length)


def _rest(length):
    return "." if length == 1 else ".:%d" % length


def _track(events, start, length, bar):
    """Notation for the events falling in ``[start, start + length)``."""
    tokens, pos = [], start
    end = start + length

    def emit(make, a, b):
        """Emit ``make(n)`` for the span a..b, broken at bar lines with holds."""
        first = True
        while a < b:
            nxt = min(b, (a // bar + 1) * bar)
            if tokens and a % bar == 0 and a != start:
                tokens.append("|")
            tokens.append(make(nxt - a) if first else ("-" if nxt - a == 1 else "-:%d" % (nxt - a)))
            first = False
            a = nxt

    def emit_rest(a, b):
        while a < b:
            nxt = min(b, (a // bar + 1) * bar)
            if tokens and a % bar == 0 and a != start:
                tokens.append("|")
            tokens.append(_rest(nxt - a))
            a = nxt

    sounded = False
    for ev_start, ev_dur, pitches in events:
        a, b = max(ev_start, start), min(ev_start + ev_dur, end)
        if a >= b:
            continue
        if a > pos:
            emit_rest(pos, a)
        emit(lambda n, p=pitches: _token(p, n), a, b)
        sounded = True
        pos = b
    if pos < end:
        emit_rest(pos, end)
    return " ".join(tokens), sounded


def _drum_track(drums, start, length, bar):
    by_step = {s: hits for s, hits in drums if start <= s < start + length}
    tokens = []
    for s in range(start, start + length):
        if s != start and s % bar == 0:
            tokens.append("|")
        hits = by_step.get(s)
        tokens.append("." if not hits else hits[0] if len(hits) == 1 else "[%s]" % " ".join(hits))
    return " ".join(tokens), bool(by_step)


def _label(i):
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return letters[i] if i < 26 else "%s%d" % (letters[i % 26], i // 26 + 1)


def to_song(arrangement, grid, bars_per_pattern=4, title=None):
    """Arrangement -> CLIo song dict."""
    bar = grid.steps_per_bar
    plen = bar * max(1, bars_per_pattern)
    total = max([e[0] + e[1] for v in arrangement.voices for e in v.events]
                + [s + 1 for s, _h in arrangement.drums] + [1])
    total = ((total + bar - 1) // bar) * bar                    # whole bars
    names = {}
    used = {}
    for v in arrangement.voices:                                # unique, stable track names
        n = v.role if v.role not in used else "%s%d" % (v.role, used[v.role] + 1)
        used[v.role] = used.get(v.role, 0) + 1
        names[id(v)] = n
    patterns, sequence, seen = {}, [], {}
    for start in range(0, total, plen):
        length = min(plen, total - start)
        tracks = {}
        for v in arrangement.voices:
            text, sounded = _track(v.events, start, length, bar)
            if sounded:
                tracks[names[id(v)]] = text
        if arrangement.drums:
            text, sounded = _drum_track(arrangement.drums, start, length, bar)
            if sounded:
                tracks["kit"] = text
        if not tracks:                                          # a silent stretch still takes time
            tracks[names[id(arrangement.voices[0])] if arrangement.voices else "lead"] = \
                _track([], start, length, bar)[0]
        key = json.dumps(tracks, sort_keys=True)
        if key not in seen:
            seen[key] = _label(len(seen))
            patterns[seen[key]] = tracks
        sequence.append(seen[key])
    instruments = {names[id(v)]: dict(v.instrument or INSTRUMENTS.get(v.role, {})) for v in arrangement.voices}
    if arrangement.drums:
        instruments["kit"] = dict(INSTRUMENTS["kit"])
    return {
        "title": title or grid.title or "untitled",
        "source": "eigenchip/%s" % (arrangement.name or "?"),
        "tempo": int(round(grid.tempo)),
        "steps_per_beat": grid.steps_per_beat,
        "volume": 0.5,
        "loop": True,
        "instruments": instruments,
        "patterns": patterns,
        "sequence": sequence,
    }


def track_length(text):
    """Number of steps a track string occupies (mirrors the CLIo parser)."""
    total, depth, buf, tokens = 0, 0, "", []
    for ch in text:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch.isspace() and depth == 0:
            if buf:
                tokens.append(buf)
            buf = ""
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    for tok in tokens:
        if tok == "|":
            continue
        length = 1
        if ":" in tok:
            length = max(1, int(float(tok.rpartition(":")[2])))
        total += length
    return total


def validate(song):
    """Check the invariants a CLIo song must hold. Returns a list of problems."""
    problems = []
    for name in song.get("sequence", []):
        if name not in song.get("patterns", {}):
            problems.append("sequence names unknown pattern '%s'" % name)
    for pname, tracks in song.get("patterns", {}).items():
        lengths = {t: track_length(text) for t, text in tracks.items()}
        if len(set(lengths.values())) > 1:
            problems.append("pattern %s: tracks differ in length %s" % (pname, lengths))
        for t in tracks:
            if t not in song.get("instruments", {}):
                problems.append("pattern %s: track '%s' has no instrument" % (pname, t))
    return problems


def dumps(song, name=None):
    """JSON text. With ``name`` the song is wrapped for pasting into music.json."""
    return json.dumps({name: song} if name else song, indent=2) + "\n"
