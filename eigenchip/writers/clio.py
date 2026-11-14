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


EXPRESSION = ("full", "plain")
SOFTEN = True
SOFT_BELOW = 2.0                # attacks a second: below this the notes get a slow attack and a long release


def _token(pitches, length, mark=""):
    body = pitch_name(pitches[0]) if len(pitches) == 1 else "[%s]" % " ".join(pitch_name(p) for p in pitches)
    return body + mark if length == 1 else "%s%s:%d" % (body, mark, length)


def _mark(levels, a, b, bend=None, key=None):
    """What CLIo 2.1 can say about a note from step a to b: ``>target`` for a slide, ``@level`` or ``@from>to``.

    ``levels`` is one level per step (measured from a sound) or a level per
    note, looked up by ``key`` = (start, pitch) (the velocities of a MIDI file).
    """
    out = ""
    if bend:
        (p0, p1), (l0, l1) = bend
        if int(round(p1)) != int(round(p0)):
            out = ">" + pitch_name(int(round(p1)))
        return out + ("@%d" % l0 if l0 == l1 else "@%d>%d" % (l0, l1))
    if not levels:
        return ""
    if isinstance(levels, dict):
        level = levels.get(key, 9)
        return "" if level >= 9 else "@%d" % level
    span = levels[a:b] or levels[-1:]
    first, last = span[0], span[-1]
    if b - a >= 4 and abs(last - first) >= 2:
        return "@%d>%d" % (first, last)                     # long enough to hear it change
    mean = int(round(sum(span) / float(len(span))))
    return "" if mean >= 9 else "@%d" % max(1, mean)


BEND = 1.5                      # levels: a held note is struck again where its loudness strays this far from a straight line
SHORTEST = 4                    # steps: but never more often than this


def _spans(levels, a, b, bend=BEND, shortest=SHORTEST):
    """Cut steps a..b where the level curve turns: ``[(a, x), (x, y), ... (z, b)]``.

    One token can say "from this level to that one" and no more. A long note
    under which the music swells and fades again would stay flat; cut where the
    curve leaves the straight line, each piece can follow it. The cost is that
    the note is struck again there.
    """
    if not levels or isinstance(levels, dict) or b - a < 2 * shortest:
        return [(a, b)]
    out, start = [], a
    while b - start >= 2 * shortest:
        end = b
        while end - start > shortest:
            span = levels[start:end] or levels[-1:]
            n = len(span) - 1
            if n < 1 or max(abs(span[i] - (span[0] + (span[-1] - span[0]) * i / float(n))) for i in range(n + 1)) <= bend:
                break
            end -= 1
        if end >= b:
            break
        end = min(end, b - shortest)                        # the last piece is long enough to be heard as one
        if end - start < shortest:
            break
        out.append((start, end))
        start = end
    out.append((start, b))
    return out


def _rest(length):
    return "." if length == 1 else ".:%d" % length


def _track(events, start, length, bar, levels=None):
    """Notation for the events falling in ``[start, start + length)``.

    An event is ``(start, steps, pitches)``; a fourth item ``((pitch, pitch), (level, level))``
    makes it a slide with a level of its own, and ``levels`` (one per step) marks
    the others. Both need CLIo 2.1.
    """
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
    for event in events:
        ev_start, ev_dur, pitches = event[:3]
        a, b = max(ev_start, start), min(ev_start + ev_dur, end)
        if a >= b:
            continue
        if a > pos:
            emit_rest(pos, a)
        bend = None
        if len(event) > 3 and event[3]:                     # cut at a pattern edge: take the part that is inside
            (p0, p1), (l0, l1) = event[3]
            f0, f1 = (a - ev_start) / float(ev_dur), (b - ev_start) / float(ev_dur)
            bend = ((p0 + (p1 - p0) * f0, p0 + (p1 - p0) * f1),
                    (int(round(l0 + (l1 - l0) * f0)), int(round(l0 + (l1 - l0) * f1))))
            pitches = [int(round(bend[0][0]))]
        for a, b in ([(a, b)] if bend else _spans(levels, a, b)):
            mark = _mark(levels, a, b, bend, (ev_start, pitches[0]))
            emit(lambda n, p=pitches, m=mark: _token(p, n, m), a, b)
        sounded = True
        pos = b
    if pos < end:
        emit_rest(pos, end)
    return " ".join(tokens), sounded


def _drum_track(drums, start, length, bar, levels=None):
    by_step = {s: hits for s, hits in drums if start <= s < start + length}
    tokens = []
    for s in range(start, start + length):
        if s != start and s % bar == 0:
            tokens.append("|")
        hits = by_step.get(s)
        mark = _mark(levels, s, s + 1) if hits and isinstance(levels, list) else ""
        tokens.append("." if not hits else (hits[0] if len(hits) == 1 else "[%s]" % " ".join(hits)) + mark)
    return " ".join(tokens), bool(by_step)


# Sounds that are not notes, as far as a note list can say them. The song format has no pitch
# slide, so a sweep becomes a staircase of short notes; an envelope whose attack outlasts the
# note gives the grow-and-stop of a reversed sound.
FX_INSTRUMENTS = {
    "fx": {"wave": "saw", "attack": 0.005, "decay": 0.05, "sustain": 0.8, "release": 0.03, "gate": 1.0,
           "volume": 0.16},
    "air": {"wave": "noise", "attack": 0.01, "decay": 0.05, "sustain": 0.8, "release": 0.04, "gate": 1.0,
            "volume": 0.18},
    "swell": {"wave": "soft", "attack": 2.0, "decay": 0.05, "sustain": 1.0, "release": 0.02, "gate": 1.0,
              "volume": 0.6},
    "hiss": {"wave": "noise", "attack": 2.0, "decay": 0.05, "sustain": 1.0, "release": 0.02, "gate": 1.0,
             "volume": 0.5},
    "boom": {"wave": "triangle", "attack": 0.002, "decay": 1.2, "sustain": 0.0, "release": 0.2, "gate": 1.0,
             "volume": 0.7},
}


# With slides and levels (CLIo 2.1) the same sounds need no tricks: the note itself moves.
FX_SLIDING = {
    "fx": {"wave": "saw", "attack": 0.01, "decay": 0.05, "sustain": 0.9, "release": 0.05, "gate": 1.0,
           "volume": 0.2},
    "air": {"wave": "noise", "attack": 0.01, "decay": 0.05, "sustain": 0.9, "release": 0.05, "gate": 1.0,
            "volume": 0.22},
    "swell": {"wave": "soft", "attack": 0.01, "decay": 0.05, "sustain": 1.0, "release": 0.02, "gate": 1.0,
              "volume": 0.3},
    "hiss": {"wave": "noise", "attack": 0.01, "decay": 0.05, "sustain": 1.0, "release": 0.02, "gate": 1.0,
             "volume": 0.3},
    "boom": dict(FX_INSTRUMENTS["boom"]),
}


def effect_slides(effects, steps_per_beat):
    """The same effects as single notes that slide and swell (CLIo 2.1): ``{track: events}``."""
    out = {}
    for e in sorted(effects or [], key=lambda e: e["start"]):
        a = int(round(e["start"] * steps_per_beat))
        b = max(a + 1, int(round(e["end"] * steps_per_beat)))
        kind, noisy = e["kind"], bool(e.get("noise"))
        top = int(min(9, max(5, round(9 * float(e.get("strength", 1.0))))))
        clip = lambda p: min(108.0, max(24.0, float(p)))    # noqa: E731
        if kind == "riser":
            track, bend = ("air" if noisy else "fx"), ((clip(e["low"]), clip(e["high"])), (max(1, top // 4), top))
        elif kind == "fall":
            track, bend = ("air" if noisy else "fx"), ((clip(e["high"]), clip(e["low"])), (top, max(1, top // 4)))
        elif kind == "swell":
            track, bend = ("hiss" if noisy else "swell"), ((clip(e["low"]), clip(e["low"])), (1, top))
        elif kind == "impact":
            track, bend, b = "boom", ((33.0, 33.0), (top, top)), max(b, a + 2 * steps_per_beat)
        else:
            continue
        events = out.setdefault(track, [])
        if events and events[-1][0] + events[-1][1] > a:    # two at once on one track: the later one waits
            a = events[-1][0] + events[-1][1]
        if b > a:
            events.append((a, b - a, [int(round(bend[0][0]))], bend))
    return out


BED_LOWEST = 24.0
BED = {"wave": "noise", "attack": 0.03, "decay": 0.05, "sustain": 1.0, "release": 0.06, "gate": 1.0, "volume": 0.25}


def texture_events(texture, per, total, full=True):
    """A noise bed from the lasting noise of the source: ``[(start, steps, [pitch], bend), ...]``.

    ``texture`` holds a level (0 to 1) and a brightness (as a MIDI pitch) per
    step of the reader; ``per`` is reader steps per song step. With ``full``
    each note slides and swells to follow them; without, it is a plain note
    wherever the noise is strong.
    """
    if not texture:
        return []
    def at(i):
        j = min(len(texture["level"]) - 1, int(i * per))
        level = int(min(9, round(9 * texture["level"][j])))
        # the chip's noise at note p has its centre near 0.78 p + 30 (measured), so ask for the note that fits
        return level, min(96.0, max(BED_LOWEST, (texture["pitch"][j] - 30.0) / 0.78))
    floor = 1 if full else 3
    out, i = [], 0
    while i < total:
        level, pitch = at(i)
        if level < floor:
            i += 1
            continue
        j = i + 1
        while j < total and j - i < (8 if full else 4) and at(j)[0] >= floor:
            j += 1
        last_level, last_pitch = at(j - 1)
        out.append((i, j - i, [int(round(pitch))], ((pitch, last_pitch), (level, last_level)) if full else None))
        i = j
    return out


def step_levels(grid, total):
    """How loud the source is, from 1 to 9 - or None when it never changes.

    A transcription carries a loudness curve measured from the sound: the
    answer is a level per step.  A MIDI file has only the velocities of its
    notes: the answer is a level per note, ``{(start, pitch): level}``, each
    against the loudest note of its own channel - the balance between the parts
    is the instruments' business, the rise and fall within a part is the notes'.
    """
    curve = grid.info.get("loudness")
    if curve:
        per = float(grid.info.get("loudness_per_beat", grid.steps_per_beat)) / grid.steps_per_beat
        levels = [int(min(9, max(1, round(9 * curve[min(len(curve) - 1, int(i * per))])))) for i in range(total)]
        return levels if any(v < 9 for v in levels) else None
    top = {}
    for n in grid.pitched:
        top[n.channel] = max(top.get(n.channel, 1), n.vel)
    levels = {(n.start, n.pitch): int(min(9, max(1, round(9.0 * n.vel / top[n.channel])))) for n in grid.pitched}
    return levels if any(v < 9 for v in levels.values()) else None


def effect_tracks(effects, steps_per_beat):
    """``{track name: events}`` for the effects of a piece (times in beats, as the audio reader leaves them)."""
    cells = {}                                              # track -> {step: (pitch, which effect)}
    for i, e in enumerate(sorted(effects or [], key=lambda e: e["start"])):
        a = int(round(e["start"] * steps_per_beat))
        b = max(a + 1, int(round(e["end"] * steps_per_beat)))
        kind, noisy = e["kind"], bool(e.get("noise"))
        if kind in ("riser", "fall"):
            track = "air" if noisy else "fx"
            lo, hi = (e["low"], e["high"]) if kind == "riser" else (e["high"], e["low"])
            path = [lo + (hi - lo) * (k + 0.5) / (b - a) for k in range(b - a)]
        elif kind == "swell":
            track, path = ("hiss" if noisy else "swell"), [e["low"]] * (b - a)
        elif kind == "impact":
            track, path = "boom", [33] * max(b - a, 2 * steps_per_beat)
        else:
            continue
        taken = cells.setdefault(track, {})
        for k, pitch in enumerate(path):
            taken.setdefault(a + k, (int(min(108, max(24, round(pitch)))), i))
    out = {}
    for track, taken in cells.items():
        events = []
        for step in sorted(taken):
            pitch, which = taken[step]
            last = events[-1] if events else None
            if last and last[0] + last[1] == step and last[2] == [pitch] and last[3] == which:
                last[1] += 1
            else:
                events.append([step, 1, [pitch], which])
        out[track] = [(s0, d, p) for s0, d, p, _which in events]
    return out


def _label(i):
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return letters[i] if i < 26 else "%s%d" % (letters[i % 26], i // 26 + 1)


def to_song(arrangement, grid, bars_per_pattern=4, title=None, effects=True, expression="full"):
    """Arrangement -> CLIo song dict.

    With ``effects``, the risers, falls, swells and impacts the audio reader
    found (``grid.info["effects"]``) are written on tracks of their own, beside
    the voices of the arrangement.

    ``expression`` says how much of the source's movement the song carries:

    ``full``   notes follow the loudness of the source, sweeps slide and swells
               swell. Needs CLIo 2.1; the song says so in ``"needs"``.
    ``plain``  every note at one level, a sweep as a staircase of short notes.
               The sound of the chip as it was, and playable by CLIo 2.0.
    """
    if expression not in EXPRESSION:
        raise ValueError("Unknown expression '%s'. Choose from: %s" % (expression, ", ".join(EXPRESSION)))
    full = expression == "full"
    bar = grid.steps_per_bar
    plen = bar * max(1, bars_per_pattern)
    found = grid.info.get("effects") if effects else None
    extra = (effect_slides if full else effect_tracks)(found, grid.steps_per_beat)
    total = max([e[0] + e[1] for v in arrangement.voices for e in v.events]
                + [e[0] + e[1] for events in extra.values() for e in events]
                + [s + 1 for s, _h in arrangement.drums] + [1])
    total = ((total + bar - 1) // bar) * bar                    # whole bars
    levels = step_levels(grid, total) if full else None
    bed = texture_events(grid.info.get("texture"), float(grid.info.get("loudness_per_beat", grid.steps_per_beat))
                         / grid.steps_per_beat, total, full) if effects else []
    if bed:
        extra = dict(extra, bed=bed)
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
            text, sounded = _track(v.events, start, length, bar, levels)
            if sounded:
                tracks[names[id(v)]] = text
        if arrangement.drums:
            text, sounded = _drum_track(arrangement.drums, start, length, bar, levels)
            if sounded:
                tracks["kit"] = text
        for name in sorted(extra):
            text, sounded = _track(extra[name], start, length, bar)
            if sounded:
                tracks[name] = text
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
    if SOFTEN and grid.info.get("attacks_per_second", 99.0) < SOFT_BELOW:
        for inst in instruments.values():                       # slow music: no hard edges on the notes
            if inst.get("wave") != "drums":
                inst.update(attack=max(inst.get("attack", 0.0), 0.08), release=max(inst.get("release", 0.0), 0.3))
    for name in sorted(extra):
        instruments[name] = dict(BED if name == "bed" else (FX_SLIDING if full else FX_INSTRUMENTS)[name])
    if "bed" in instruments and not full:
        instruments["bed"]["volume"] = 0.15                     # no levels to follow: keep it in the background
    moving = full and (levels is not None or bool(extra))
    return dict(([("needs", "CLIo 2.1 (slides and levels)")] if moving else []), **{
        "title": title or grid.title or "untitled",
        "source": "eigenchip/%s" % (arrangement.name or "?"),
        "tempo": int(round(grid.tempo)),
        "steps_per_beat": grid.steps_per_beat,
        "volume": 0.5,
        "loop": True,
        "instruments": instruments,
        "patterns": patterns,
        "sequence": sequence,
    })


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
