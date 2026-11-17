# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""A tune that was hummed, sung or whistled into a microphone, as notes for the composer.

One voice, nothing else.  A voice is not tuned to a piano: it sits a little
above or below, and it sinks or rises as the tune goes on.  So first its own
tuning is measured - how far the pitch lies from the nearest tempered note,
averaged over a few seconds at a time - and the recording is bent so that it
sits on the notes.  Then the strongest line is followed (``transcribe_mono``),
and the things a voice does that a written tune does not are taken out:

* **blips** - breath, a consonant, a crack - are dropped;
* a **scoop** (the voice slides into a note from just below, or falls off it at
  the end) is heard as a short neighbouring note; it is given to the note it
  belongs to;
* the **tempo** of the humming is not the one set: the beat is fitted near it,
  as the one on whose eighths the notes fall best;
* **time** begins with the first note, and every note is put on the sixteenth
  nearest to it; a short gap before the next note is the singer's breath, and
  the note is written through it; before a rest and at the end, where a voice
  lets go early, a note a sixteenth short of a half beat is given that sixteenth;
* a voice is low and a chip's tune is not: the whole line is moved by octaves
  until its middle lies in the octave above middle C.

What comes out is ``(start, length, pitch)`` in beats, for ``readers.tune.read_notes``.
It is a first draft to be mended on the piano roll: a voice that drifts in
pitch, slides between notes or wavers widely will leave wrong notes.
"""
from __future__ import annotations

import math

from . import RATE, need_numpy
from .transcribe import Spectrum, transcribe_mono

LOW, HIGH = 36, 88              # C2 to E6: a low voice to a whistle
BLIP = 0.09                     # seconds: anything shorter is not a note
SCOOP = 0.16                    # seconds: a neighbour this short, touching a longer note, is a slide into or off it
TOUCH = 0.06                    # seconds between two notes that still counts as touching
NEAR = 2                        # semitones: how far a scoop may be from its note
STRETCH = (0.8, 1.25)           # how far the hummed tempo may lie from the one set
GRID = 0.25                     # beats: a sixteenth
BREATH = 0.5                    # beats: a gap this short before the next note is the singer's breath, not a rest
MIDDLE = (60, 72)               # the octave the middle of the line is moved into
FRAME = 0.064                   # seconds of sound in which the pitch is measured, every half of that
VOICE = (60.0, 2100.0)          # Hz: a low hum to a high whistle
WAVER = 0.1                     # seconds either side over which a wavering pitch is averaged: about one wave
SPAN = 3.0                      # seconds over which the voice's tuning is averaged
SURE = 0.3                      # below this agreement within a span the tuning is not trusted there


def tuning(samples, rate):
    """``(seconds, semitones)``: how far above the tempered notes the voice lies, as it changes through the
    recording - two arrays, one value every half ``FRAME``.  Empty when no pitch was found."""
    np = need_numpy()
    size = int(rate * FRAME)
    hop = size // 2
    if len(samples) < 2 * size:
        return np.zeros(0), np.zeros(0)
    window = np.hanning(size)
    short, long_ = max(2, int(rate / VOICE[1])), min(size - 2, int(rate / VOICE[0]))
    frames = [samples[a:a + size] for a in range(0, len(samples) - size, hop)]
    loud = np.array([float(np.sqrt(np.mean(f * f))) for f in frames])
    floor = 0.25 * float(np.percentile(loud, 90))
    times, heard = [], []
    for k, frame in enumerate(frames):
        if loud[k] < floor or loud[k] <= 0:
            continue
        spectrum = np.fft.rfft(frame * window, 2 * size)
        same = np.fft.irfft(spectrum * np.conj(spectrum))[:size]       # how like itself the sound is, lag by lag
        if same[0] <= 0:
            continue
        same = same / same[0]
        peaks = [i for i in range(short, long_) if same[i] > same[i - 1] and same[i] >= same[i + 1]]
        if not peaks:
            continue
        top = max(same[i] for i in peaks)
        if top < 0.5:                                                   # no clear pitch: breath, a consonant
            continue
        lag = next(i for i in peaks if same[i] >= 0.9 * top)            # the shortest of the good ones: not an octave below
        a, b, c = same[lag - 1], same[lag], same[lag + 1]
        fine = lag + (0.5 * (a - c) / (a - 2 * b + c) if a - 2 * b + c else 0.0)
        times.append((k * hop + size / 2.0) / rate)
        heard.append(69 + 12 * math.log2(rate / fine / 440.0))
    if len(times) < 4:
        return np.zeros(0), np.zeros(0)
    times, heard = np.array(times), np.array(heard)
    turn = np.zeros(len(times))
    for i, t in enumerate(times):                                       # a wavering voice means the middle of its wave
        same_note = (np.abs(times - t) <= WAVER) & (np.abs(heard - heard[i]) < 1.0)
        middle = float(np.mean(heard[same_note]))
        turn[i] = 2 * math.pi * (middle - round(middle))
    out = np.zeros(len(times))
    for i, t in enumerate(times):                                       # the mean over a span, around the circle
        near = np.abs(times - t) <= SPAN / 2
        x, y = float(np.mean(np.cos(turn[near]))), float(np.mean(np.sin(turn[near])))
        out[i] = math.atan2(y, x) / (2 * math.pi) if math.hypot(x, y) >= SURE else float("nan")
    known = ~np.isnan(out)
    if not known.any():
        return np.zeros(0), np.zeros(0)
    out = np.interp(times, times[known], np.unwrap(out[known], period=1.0))
    return times, out


def in_tune(samples, rate):
    """``(samples, clock)``: the recording bent onto the tempered notes, and ``clock(seconds)`` giving for a time in
    the bent recording the time in the one that was made."""
    np = need_numpy()
    times, off = tuning(samples, rate)
    if not len(times) or float(np.max(np.abs(off))) < 0.05:
        return samples, lambda t: t
    at = np.arange(len(samples)) / float(rate)
    faster = 2.0 ** (-np.interp(at, times, off) / 12.0)                # a flat voice is played a little faster
    bent = np.concatenate([[0.0], np.cumsum(1.0 / faster)[:-1]])       # where each sample lands in the bent one
    out = np.interp(np.arange(int(bent[-1]) + 1), bent, samples).astype(np.float32)
    return out, lambda t: float(np.interp(t * rate, bent, at))


def _mend(heard):
    """Drop blips, give scoops to their notes.  ``heard``: ``(onset, offset, pitch, strength)``, in order."""
    notes = [list(n[:3]) for n in sorted(heard) if n[1] - n[0] >= BLIP / 2]
    out = []
    for i, (on, off, pitch) in enumerate(notes):
        short = off - on < SCOOP
        after = notes[i + 1] if i + 1 < len(notes) else None
        if short and after and after[0] - off <= TOUCH and 0 < abs(after[2] - pitch) <= NEAR \
                and after[1] - after[0] > off - on:
            after[0] = on                                   # a slide into the next note: that note began here
            continue
        if short and out and on - out[-1][1] <= TOUCH and 0 < abs(out[-1][2] - pitch) <= NEAR \
                and out[-1][1] - out[-1][0] > off - on:
            out[-1][1] = off                                # a fall off the note before: it lasted until here
            continue
        if off - on >= BLIP:
            out.append([on, off, pitch])
    return out


def _fit(onsets, tempo):
    """The tempo near ``tempo`` on whose eighths the onsets (seconds from the first) fall best."""
    if len(onsets) < 4:
        return float(tempo)
    best, best_miss = float(tempo), None
    for k in range(int(STRETCH[0] * 100), int(STRETCH[1] * 100) + 1):
        t = tempo * k / 100.0
        miss = 0.0
        for s in onsets:
            eighths = s * t / 30.0
            miss += (eighths - round(eighths)) ** 2
        miss = miss / len(onsets) + 0.02 * abs(k / 100.0 - 1.0)     # when in doubt, the tempo that was set
        if best_miss is None or miss < best_miss:
            best, best_miss = t, miss
    return best


def notes(samples, rate=RATE, tempo=100.0, progress=None, grid=GRID):
    """``(notes, tempo)``: the hummed tune as ``(start, length, pitch)`` in beats, and the tempo it was hummed at.
    ``grid``: the note value in beats that starts and lengths are put on - a sixteenth unless a coarser one is
    asked for (0.5 an eighth, 1 a quarter), which forgives a voice more and cannot write quick notes."""
    if grid not in (0.25, 0.5, 1.0):
        raise ValueError("Notes are put on sixteenths (0.25), eighths (0.5) or quarters (1) of a beat.")
    samples, clock = in_tune(samples, rate)
    spec = Spectrum(samples, rate, progress=progress)
    heard = [[clock(on), clock(off), pitch] for on, off, pitch in _mend(transcribe_mono(spec, low=LOW, high=HIGH))]
    if not heard:
        raise ValueError("No tune was heard. Hum or sing closer to the microphone, one note after another.")
    first = heard[0][0]
    found = _fit([n[0] - first for n in heard], float(tempo))
    beat = 60.0 / found
    middle = sorted(n[2] for n in heard)[len(heard) // 2]
    shift = 0
    while middle + shift < MIDDLE[0]:
        shift += 12
    while middle + shift > MIDDLE[1]:
        shift -= 12
    out = []
    for on, off, pitch in heard:
        start = round((on - first) / beat / grid) * grid
        length = max(grid, round((off - on) / beat / grid + (0.25 if grid > GRID else 0.0)) * grid)   # a voice lets go early
        if out and start <= out[-1][0]:                     # two on one sixteenth: the longer one stays
            if length > out[-1][1]:
                out[-1] = [out[-1][0], length, pitch + shift]
            continue
        if out and (out[-1][0] + out[-1][1] > start         # one voice: a note ends where the next begins,
                    or start - out[-1][0] - out[-1][1] <= min(BREATH, out[-1][1])):     # and a breath is not a rest
            out[-1][1] = start - out[-1][0]
        out.append([start, length, pitch + shift])
    for i, note in enumerate(out):                          # before a rest and at the end a voice lets go early:
        room = out[i + 1][0] - note[0] - note[1] if i + 1 < len(out) else GRID
        if grid == GRID and room >= GRID and note[1] % (2 * GRID) == GRID and note[1] > GRID:
            note[1] += GRID                                 # three sixteenths were meant as a half beat
    return [tuple(n) for n in out], found
