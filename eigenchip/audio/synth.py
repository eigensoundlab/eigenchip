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
    "pad": ([1.0, 0.5, 0.28, 0.16, 0.1, 0.06], 0.45, 0.0, 0.6),      # swells in, lingers
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


# ---------------------------------------------------------------------- #
# sounds that are not notes: the stock effects of film and ambient music
# ---------------------------------------------------------------------- #
EFFECTS = ("riser", "fall", "swell", "impact")

# One of each, spread over half a minute: the test scene of the experiments (times in seconds).
EFFECT_DEMO = [
    {"kind": "riser", "start": 2.0, "end": 5.0, "low": 48, "high": 84},
    {"kind": "impact", "start": 5.05, "end": 6.5},
    {"kind": "riser", "start": 8.0, "end": 10.0, "low": 55, "high": 91, "noise": True},
    {"kind": "swell", "start": 11.5, "end": 13.0, "low": 57},
    {"kind": "fall", "start": 15.0, "end": 16.5, "low": 50, "high": 80},
    {"kind": "swell", "start": 18.5, "end": 19.5, "low": 60, "noise": True},
    {"kind": "impact", "start": 21.0, "end": 22.5},
    {"kind": "riser", "start": 24.0, "end": 28.0, "low": 40, "high": 70},
]


def effect(kind, seconds, low=48, high=84, noise=False, rate=RATE, seed=0):
    """One effect as samples, peak about 1.

    riser   a pitch (or a band of noise) sliding up from ``low`` to ``high``, growing louder
    fall    the same downwards, fading
    swell   a sound played backwards: it grows out of nothing and stops dead (pitch ``low``)
    impact  a thud with a long low tail
    """
    np = need_numpy()
    rng = np.random.RandomState(seed)
    n = max(1, int(seconds * rate))
    t = np.arange(n) / float(rate)
    x = t / max(seconds, 1e-6)
    if kind in ("riser", "fall"):
        a, b = (low, high) if kind == "riser" else (high, low)
        pitch = a + (b - a) * x
        loud = 0.15 + 0.85 * x if kind == "riser" else 1.0 - 0.8 * x
        if noise:
            out = _sliding_noise(np, rng, pitch, rate)
        else:
            phase = 2 * math.pi * np.cumsum(440.0 * 2.0 ** ((pitch - 69) / 12.0)) / rate
            out = np.sin(phase) + 0.4 * np.sin(2 * phase) + 0.2 * np.sin(3 * phase)
        out = out * loud
    elif kind == "swell":
        grow = np.exp(5.0 * (x - 1.0))                      # a decay, turned round
        if noise:
            out = rng.uniform(-1, 1, n) * grow
        else:
            f = midi_hz(low)
            out = (np.sin(2 * math.pi * f * t) + 0.5 * np.sin(4 * math.pi * f * t)
                   + 0.3 * np.sin(6 * math.pi * f * t)) * grow
    elif kind == "impact":
        thud = np.sin(2 * math.pi * (38.0 * t + 22.0 * (1 - np.exp(-t * 12)) / 12)) * np.exp(-t * 2.2)
        crack = rng.uniform(-1, 1, n) * np.exp(-t * 30) * 0.9
        rumble = np.sin(2 * math.pi * 76.0 * t) * np.exp(-t * 3.5) * 0.4
        out = thud + crack + rumble
    else:
        raise ValueError("Unknown effect '%s'. Choose from: %s" % (kind, ", ".join(EFFECTS)))
    edge = min(n // 2, int(0.004 * rate))                   # no click at the very start
    if edge:
        out[:edge] *= np.linspace(0.0, 1.0, edge)
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / peak).astype(np.float32)


def _sliding_noise(np, rng, pitch, rate, block=2048):
    """Noise about an octave wide whose centre follows ``pitch`` (MIDI numbers, one per sample)."""
    n = len(pitch)
    hop = block // 2
    out = np.zeros(n + block)
    window = np.hanning(block)
    freqs = np.fft.rfftfreq(block, 1.0 / rate)
    for start in range(0, n, hop):
        centre = midi_hz(float(pitch[min(n - 1, start + hop)]))
        shape = np.exp(-0.5 * (np.log2(np.maximum(freqs, 1.0) / centre) / 0.35) ** 2)
        spectrum = shape * np.exp(2j * math.pi * rng.uniform(0, 1, len(freqs)))
        out[start:start + block] += np.fft.irfft(spectrum, block) * window
    return out[:n]


def scene(score, effects, colour="band", rate=RATE, drums=True, level=0.5):
    """A piece with effects laid over it. ``effects``: dicts with kind, start, end (seconds), low, high, noise.

    ``score`` may be None for the effects alone. Returns the samples; the list
    passed in is the right answer for a detector.
    """
    np = need_numpy()
    base = render(score, colour, rate, drums) if score is not None else np.zeros(1, dtype=np.float32)
    end = max([len(base)] + [int((e["end"] + 0.5) * rate) for e in effects])
    out = np.zeros(end)
    out[:len(base)] = base
    for i, e in enumerate(effects):
        w = effect(e["kind"], e["end"] - e["start"], e.get("low", 48), e.get("high", 84), bool(e.get("noise")),
                   rate, seed=i + 1) * level * float(e.get("level", 1.0))
        at = int(e["start"] * rate)
        out[at:at + len(w)] += w[:max(0, end - at)]
    peak = float(np.max(np.abs(out)))
    if peak > 0.98:
        out *= 0.98 / peak
    return out.astype(np.float32)
