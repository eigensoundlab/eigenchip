# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""A reference synthesizer: audio in which every note is known.

To measure a transcriber you need recordings with the right answer attached.
This module makes them: it plays a ``Score`` with simple additive voices, so
the corpus that already has known melodies and basses also has known audio.

It is a measuring instrument, not a musical one, and it flatters the
transcribers: no room, no vibrato, exact tuning, clean attacks, and every note
is let go a little before the next one starts.  Scores on this audio are an
upper bound on what the same code does with a recording.
"""
from __future__ import annotations

import math

from . import RATE, need_numpy

# name -> (harmonic amplitudes, attack s, decay per second (0 = sustained), release s)
TIMBRES = {
    "sine": ([1.0], 0.008, 0.0, 0.04),
    "triangle": ([1.0 / (h * h) if h % 2 else 0.0 for h in range(1, 16)], 0.008, 0.0, 0.04),
    "square": ([1.0 / h if h % 2 else 0.0 for h in range(1, 24)], 0.004, 0.0, 0.03),
    "saw": ([1.0 / h for h in range(1, 24)], 0.004, 0.0, 0.03),
    "organ": ([1.0, 0.6, 0.35, 0.25, 0.1, 0.08], 0.012, 0.0, 0.06),
    "pluck": ([1.0 / h for h in range(1, 16)], 0.002, 3.0, 0.05),
}
BAND = ["saw", "organ", "triangle", "square", "pluck"]      # one voice per channel in the "band" setting


def midi_hz(pitch):
    return 440.0 * 2.0 ** ((pitch - 69) / 12.0)


GATE = 0.9          # a note sounds for this share of its written length, as a player would articulate it


def tone(np, pitch, seconds, timbre, rate):
    amps, attack, decay, release = TIMBRES[timbre]
    seconds = max(0.03, seconds * GATE - release)
    n = max(1, int(round((seconds + release) * rate)))
    t = np.arange(n) / float(rate)
    f0 = midi_hz(pitch)
    out = np.zeros(n)
    for h, a in enumerate(amps, 1):
        if a and f0 * h < rate * 0.45:
            wave = a * np.sin(2 * math.pi * f0 * h * t)
            if decay:
                wave *= np.exp(-decay * (1 + 0.35 * (h - 1)) * t)   # upper partials die first
            out += wave
    env = np.minimum(1.0, t / attack)
    tail = np.clip((seconds + release - t) / release, 0.0, 1.0)
    return out * env * tail / max(1e-9, sum(abs(a) for a in amps) ** 0.5)


def drum(np, pitch, rate, rng):
    """Kick, snare or hat, by General MIDI note number."""
    if pitch in (35, 36):
        n = int(0.16 * rate)
        t = np.arange(n) / float(rate)
        return np.sin(2 * math.pi * (45 * t + 60 * (1 - np.exp(-t * 30)) / 30)) * np.exp(-t * 22) * 1.4
    if pitch in (38, 40, 37, 39):
        n = int(0.14 * rate)
        t = np.arange(n) / float(rate)
        return (rng.uniform(-1, 1, n) * 0.8 + np.sin(2 * math.pi * 185 * t) * 0.5) * np.exp(-t * 28)
    n = int((0.22 if pitch == 46 else 0.05) * rate)
    t = np.arange(n) / float(rate)
    noise = rng.uniform(-1, 1, n)
    noise = noise - np.concatenate(([0.0], noise[:-1]))             # crude high-pass
    return noise * np.exp(-t * (14 if pitch == 46 else 70)) * 0.5


def render(score, timbre="band", rate=RATE, drums=True, seed=0, tail=0.4):
    """Play a Score. ``timbre`` is a name from TIMBRES, or "band" for a different one per channel."""
    np = need_numpy()
    rng = np.random.RandomState(seed)
    spb = 60.0 / score.tempo
    total = int((score.length * spb + tail) * rate) + 1
    out = np.zeros(total)
    channels = score.channels()
    for n in score.notes:
        at = int(round(n.start * spb * rate))
        if n.drum:
            if not drums:
                continue
            w = drum(np, n.pitch, rate, rng) * (n.vel / 127.0) * 0.5
        else:
            name = BAND[channels.index(n.channel) % len(BAND)] if timbre == "band" else timbre
            w = tone(np, n.pitch, n.dur * spb, name, rate) * (n.vel / 127.0) * 0.25
        end = min(total, at + len(w))
        if end > at:
            out[at:end] += w[:end - at]
    peak = float(np.max(np.abs(out))) if total else 0.0
    if peak > 0.98:
        out *= 0.98 / peak
    return out.astype(np.float32)


def truth(score, drums=False):
    """The notes of a Score in seconds: ``[(onset, offset, pitch), ...]``."""
    spb = 60.0 / score.tempo
    return sorted((n.start * spb, n.end * spb, n.pitch) for n in score.notes if n.drum == drums)
