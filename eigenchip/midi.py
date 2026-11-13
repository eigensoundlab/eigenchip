# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Standard MIDI Files, read and written with the standard library only."""
from __future__ import annotations

import struct

from .ir import Note, Score


class MidiError(ValueError):
    pass


def _varlen(data, pos):
    value = 0
    while True:
        if pos >= len(data):
            raise MidiError("unexpected end of track")
        b = data[pos]
        pos += 1
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            return value, pos


def read_midi(path):
    """Read a .mid file (format 0 or 1) into a Score."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"MThd":
        raise MidiError("%s is not a MIDI file" % path)
    hlen, fmt, ntracks, division = struct.unpack(">IHHH", data[4:14])
    if division & 0x8000:
        raise MidiError("SMPTE time division is not supported")
    if fmt > 1:
        raise MidiError("MIDI format %d is not supported (only 0 and 1)" % fmt)
    pos = 8 + hlen
    notes, tempos, meters, names = [], [], [], {}
    title = ""
    last_tick = 0
    for track_no in range(ntracks):
        while pos + 8 <= len(data) and data[pos:pos + 4] != b"MTrk":      # skip alien chunks
            pos += 8 + struct.unpack(">I", data[pos + 4:pos + 8])[0]
        if pos + 8 > len(data):
            break
        tlen = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        track = data[pos + 8:pos + 8 + tlen]
        pos += 8 + tlen
        tick, i, status = 0, 0, 0
        open_notes = {}                     # (channel, pitch) -> [(start, vel)]
        programs = {}
        track_name = ""
        channels_here = set()
        while i < len(track):
            delta, i = _varlen(track, i)
            tick += delta
            b = track[i]
            if b == 0xFF:                                           # meta event
                kind = track[i + 1]
                length, i = _varlen(track, i + 2)
                payload = track[i:i + length]
                i += length
                if kind == 0x51 and length == 3:
                    tempos.append((tick, int.from_bytes(payload, "big")))
                elif kind == 0x58 and length >= 2:
                    meters.append((tick, (payload[0], 2 ** payload[1])))
                elif kind == 0x03:
                    track_name = payload.decode("latin-1", "replace").strip()
                    if track_no == 0 and not title:
                        title = track_name
                elif kind == 0x2F:
                    break
                continue
            if b in (0xF0, 0xF7):                                   # sysex
                length, i = _varlen(track, i + 1)
                i += length
                continue
            if b & 0x80:
                status = b
                i += 1
            elif not status:
                raise MidiError("running status without a status byte")
            kind, ch = status & 0xF0, status & 0x0F
            if kind in (0xC0, 0xD0):
                d1, d2 = track[i], 0
                i += 1
            else:
                d1, d2 = track[i], track[i + 1]
                i += 2
            if kind == 0xC0:
                programs[ch] = d1
            elif kind == 0x90 and d2 > 0:
                open_notes.setdefault((ch, d1), []).append((tick, d2))
                channels_here.add(ch)
            elif kind == 0x80 or (kind == 0x90 and d2 == 0):
                stack = open_notes.get((ch, d1))
                if stack:
                    start, vel = stack.pop(0)
                    notes.append((start, max(1, tick - start), d1, vel, ch, programs.get(ch, 0)))
        for (ch, pitch), stack in open_notes.items():               # notes never switched off
            for start, vel in stack:
                notes.append((start, max(1, tick - start), pitch, vel, ch, programs.get(ch, 0)))
        if track_name:
            for ch in channels_here:
                names.setdefault(ch, track_name)
        last_tick = max(last_tick, tick)

    # one tempo for the whole piece: the one in force for the longest time
    end_tick = max((s + d for s, d, *_ in notes), default=last_tick)
    tempos.sort()
    if not tempos or tempos[0][0] > 0:
        tempos.insert(0, (0, 500000))
    spans = {}
    for k, (tick, usec) in enumerate(tempos):
        nxt = tempos[k + 1][0] if k + 1 < len(tempos) else max(end_tick, tick + 1)
        spans[usec] = spans.get(usec, 0) + max(0, min(nxt, max(end_tick, 1)) - tick)
    usec = max(spans, key=lambda u: spans[u])
    meters.sort()
    score_notes = [Note(s / division, d / division, p, v, ch, prog, drum=(ch == 9))
                   for s, d, p, v, ch, prog in notes]
    info = {"format": fmt, "tracks": ntracks, "division": division,
            "tempo_changes": max(0, len({u for _t, u in tempos}) - 1),
            "meter_changes": max(0, len({m for _t, m in meters}) - 1)}
    return Score(score_notes, 60000000.0 / usec, meters[0][1] if meters else (4, 4), title, names, info)


def _vlq(value):
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(out))


def write_midi(path, score, division=480):
    """Write a Score as a format-1 MIDI file, one track per channel."""
    def chunk(events):
        events.sort(key=lambda e: (e[0], e[1]))
        body, last = bytearray(), 0
        for tick, _order, payload in events:
            body += _vlq(tick - last) + payload
            last = tick
        body += b"\x00\xff\x2f\x00"
        return b"MTrk" + struct.pack(">I", len(body)) + bytes(body)

    num, den = score.meter
    conductor = [
        (0, 0, b"\xff\x03" + _vlq(len(score.title.encode("latin-1", "replace"))) + score.title.encode("latin-1", "replace")),
        (0, 1, b"\xff\x51\x03" + int(round(60000000.0 / score.tempo)).to_bytes(3, "big")),
        (0, 2, b"\xff\x58\x04" + bytes([num, den.bit_length() - 1, 24, 8])),
    ]
    tracks = [chunk(conductor)]
    for ch in sorted({n.channel for n in score.notes}):
        events = []
        name = score.names.get(ch, "")
        if name:
            raw = name.encode("latin-1", "replace")
            events.append((0, 0, b"\xff\x03" + _vlq(len(raw)) + raw))
        mine = [n for n in score.notes if n.channel == ch]
        if ch != 9:
            events.append((0, 1, bytes([0xC0 | ch, mine[0].program & 0x7F])))
        for n in mine:
            on = int(round(n.start * division))
            off = max(on + 1, int(round(n.end * division)))
            events.append((on, 3, bytes([0x90 | ch, n.pitch & 0x7F, max(1, min(127, n.vel))])))
            events.append((off, 2, bytes([0x80 | ch, n.pitch & 0x7F, 0])))
        tracks.append(chunk(events))
    with open(path, "wb") as f:
        f.write(b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), division) + b"".join(tracks))
    return path
