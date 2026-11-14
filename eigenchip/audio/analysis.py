# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Spectrogram, onset strength, tempo and the step grid.

Nothing here is new: a short-time Fourier transform, spectral flux, and tempo
by autocorrelation are textbook tools.  They are written out plainly so that
the transcribers built on them can be read from top to bottom.
"""
from __future__ import annotations

import math

from . import RATE, need_numpy


def stft(x, n_fft=4096, hop=512, max_hz=None, rate=RATE):
    """Magnitude spectrogram ``[frames, bins]``; frame ``i`` is centred on sample ``i * hop``."""
    np = need_numpy()
    pad = n_fft // 2
    xp = np.concatenate((np.zeros(pad, dtype=np.float32), np.asarray(x, dtype=np.float32),
                         np.zeros(pad, dtype=np.float32)))
    frames = 1 + max(0, (len(xp) - n_fft) // hop)
    bins = n_fft // 2 + 1
    if max_hz:
        bins = min(bins, int(max_hz * n_fft / float(rate)) + 1)
    window = np.hanning(n_fft).astype(np.float32)
    out = np.empty((frames, bins), dtype=np.float32)
    offsets = np.arange(n_fft)[None, :]
    for a in range(0, frames, 256):                     # in blocks, to keep memory flat on long files
        b = min(frames, a + 256)
        idx = offsets + (hop * np.arange(a, b))[:, None]
        out[a:b] = np.abs(np.fft.rfft(xp[idx] * window, axis=1))[:, :bins]
    return out


def median_filter(np, a, size, axis):
    """Running median along one axis (edges padded by reflection)."""
    half = size // 2
    pad = [(0, 0)] * a.ndim
    pad[axis] = (half, half)
    padded = np.pad(a, pad, mode="reflect")
    out = np.empty_like(a)
    block = 512 if axis == 0 else a.shape[0]
    if axis == 0:
        for lo in range(0, a.shape[0], block):          # in blocks: the windowed copy is `size` times larger
            hi = min(a.shape[0], lo + block)
            idx = np.arange(lo, hi)[:, None] + np.arange(size)[None, :]
            out[lo:hi] = np.median(padded[idx], axis=1)
    else:
        for lo in range(0, a.shape[0], 256):
            hi = min(a.shape[0], lo + 256)
            idx = np.arange(a.shape[1])[:, None] + np.arange(size)[None, :]
            out[lo:hi] = np.median(padded[lo:hi][:, idx], axis=2)
    return out


def harmonic_part(mag, fps, seconds=0.2, bins=17):
    """Keep what is steady in time (tones), drop what is spread across frequency (hits).

    Harmonic-percussive separation by median filtering (Fitzgerald, 2010): a
    tone is a horizontal line in the spectrogram, a drum hit a vertical one.
    """
    np = need_numpy()
    size = max(3, int(round(seconds * fps)) | 1)
    steady = median_filter(np, mag, size, 0)
    burst = median_filter(np, mag, bins, 1)
    mask = steady ** 2 / (steady ** 2 + burst ** 2 + 1e-12)
    return mag * mask


def flux_of(mag):
    """Spectral flux of a magnitude spectrogram: how much new energy arrives in each frame (0..1)."""
    np = need_numpy()
    mag = np.log1p(40.0 * mag)
    flux = np.maximum(0.0, mag[1:] - mag[:-1]).sum(axis=1)
    flux = np.concatenate(([0.0], flux))
    span = max(3, int(0.4 * 86.0)) | 1                     # subtract the local average: keep the peaks
    local = np.convolve(flux, np.ones(span) / span, mode="same")
    flux = np.maximum(0.0, flux - local)
    top = float(flux.max()) if len(flux) else 0.0
    return flux / top if top > 0 else flux


def onset_strength(x, rate=RATE, n_fft=1024, hop=256):
    """Onset strength of a signal, from a short-window spectrogram. Returns ``(flux, frames per second)``."""
    return flux_of(stft(x, n_fft, hop, rate=rate)), rate / float(hop)


def noise_floor(np, mag, bin_hz, edges, share=0.3):
    """How much of each band is noise: ``[frames, bands]`` amplitudes.

    Tones are a few tall bins with nothing between them; noise fills every bin.
    So the level of a band's *quieter* bins tells how much noise is in it, and
    tones hardly move that figure.  ``edges`` are band limits in Hz.  The low
    quantile is scaled so that for pure noise the result is the band's whole
    amplitude.
    """
    out = np.zeros((mag.shape[0], len(edges) - 1), dtype=np.float32)
    scale = math.sqrt(2.0 / (-2.0 * math.log(1.0 - share)))        # Rayleigh: quantile -> root mean square
    for k in range(len(edges) - 1):
        a, b = int(math.ceil(edges[k] / bin_hz)), int(math.ceil(edges[k + 1] / bin_hz))
        b = min(b, mag.shape[1])
        if b - a < 5:                                               # too few bins to tell a tone from noise
            continue
        cut = np.partition(mag[:, a:b], int(share * (b - a)), axis=1)[:, int(share * (b - a))]
        out[:, k] = cut * scale * math.sqrt(b - a)
    return out


def log_matrix(np, n_linear, bin_hz, centres, bins_per_semitone):
    """``[log bins, linear bins]``: how to gather a linear spectrum into bins spaced evenly in pitch.

    Low down, where linear bins are wider than the pitch bins, this interpolates;
    high up, where many linear bins fall into one pitch bin, it pools them.
    """
    out = np.zeros((len(centres), n_linear), dtype=np.float32)
    index = np.arange(n_linear)
    half = 2.0 ** (1.0 / (12.0 * bins_per_semitone))
    for k, fc in enumerate(centres):
        pos = fc / bin_hz
        width = max(1.0, (fc * half - fc / half) / bin_hz)          # in linear bins
        lo, hi = max(0, int(pos - width) - 1), min(n_linear, int(pos + width) + 2)
        if hi <= lo:
            continue
        # not normalised: where it pools, the energies of the lines in the band add up,
        # so a single partial keeps its height however wide the band is
        out[k, lo:hi] = np.maximum(0.0, 1.0 - np.abs(index[lo:hi] - pos) / width)
    return out


def peaks(np, curve, floor=0.08, spread=2):
    """Indices of local maxima above ``floor``."""
    out = []
    n = len(curve)
    for i in range(n):
        v = curve[i]
        if v < floor:
            continue
        a, b = max(0, i - spread), min(n, i + spread + 1)
        if v >= curve[a:b].max() and (i == 0 or v > curve[i - 1]):
            out.append(i)
    return out


def _comb(np, flux, fps, bpm, phases):
    """Mean flux on the beats (and, at half weight, between them) for every phase offered."""
    period = 60.0 / bpm * fps
    count = int((len(flux) - 1 - phases.max()) / period)
    if count < 4:
        return np.zeros(len(phases))
    k = np.arange(count)[None, :]
    grid = np.arange(len(flux))
    on = np.interp((phases[:, None] + k * period).ravel(), grid, flux).reshape(len(phases), count)
    off = np.interp((phases[:, None] + (k + 0.5) * period).ravel(), grid, flux).reshape(len(phases), count)
    return on.mean(axis=1) + 0.5 * off.mean(axis=1)


def estimate_tempo(flux, fps, low=50.0, high=210.0, prior=110.0):
    """Tempo and the time of the first beat. Returns ``(bpm, offset seconds, confidence 0..1)``.

    Autocorrelation of the onset strength finds the period.  Slow and fast
    readings of the same pulse (60 against 120) both fit, so a gentle
    preference for tempos near ``prior`` decides between them; this is a
    guess, and the most common error of any tempo estimator.
    """
    np = need_numpy()
    n = len(flux)
    if n < int(fps * 2) or not float(np.max(flux)) > 0:
        return 120.0, 0.0, 0.0
    f = flux - flux.mean()
    size = 1 << int(math.ceil(math.log(2 * n, 2)))
    ac = np.fft.irfft(np.abs(np.fft.rfft(f, size)) ** 2)[:n]
    ac = ac / ac[0] if ac[0] > 0 else ac
    lags = np.arange(n)
    best, best_score = prior, -1e9
    for bpm in np.arange(low, high + 0.25, 0.5):
        lag = 60.0 / bpm * fps
        if 4 * lag >= n:
            continue
        score = np.interp(lag, lags, ac) + 0.5 * np.interp(2 * lag, lags, ac) + 0.25 * np.interp(4 * lag, lags, ac)
        score *= math.exp(-0.5 * (math.log(bpm / prior, 2) / 0.9) ** 2)
        if score > best_score:
            best, best_score = float(bpm), float(score)
    # sharpen: a comb over the whole file resolves tempo far more finely than the autocorrelation
    period = 60.0 / best * fps
    phases = np.arange(0.0, period, 0.5)
    top = (-1.0, best, 0.0)
    for bpm in np.arange(best * 0.985, best * 1.015, best * 0.0005):
        ph = np.arange(0.0, 60.0 / bpm * fps, 0.5)
        score = _comb(np, flux, fps, bpm, ph)
        i = int(np.argmax(score))
        if score[i] > top[0]:
            top = (float(score[i]), float(bpm), float(ph[i]))
    lag = 60.0 / top[1] * fps
    confidence = max(0.0, min(1.0, float(np.interp(lag, lags, ac))))      # how periodic the onsets are
    return top[1], top[2] / fps, confidence


def beat_phase(flux, fps, bpm):
    """Time of the first beat for a tempo that is already known."""
    np = need_numpy()
    phases = np.arange(0.0, 60.0 / bpm * fps, 0.5)
    if not len(flux) or not len(phases):
        return 0.0
    return float(phases[int(np.argmax(_comb(np, flux, fps, bpm, phases)))]) / fps


def settle_phase(flux, fps, bpm, offset, first_onset, steps_per_beat=4):
    """Choose which step of the grid is the beat.

    The flux comb says where the beats are, but in even running notes every
    step looks like a beat.  Music usually begins on one, so the phase that
    puts the first note on a beat wins unless the comb clearly prefers another
    (an upbeat at the start).
    """
    np = need_numpy()
    step = 60.0 / bpm / steps_per_beat
    beat = 60.0 / bpm
    fine = offset % step
    options = [fine + k * step for k in range(steps_per_beat)]
    score = _comb(np, flux, fps, bpm, np.asarray(options) * fps)
    best = int(np.argmax(score))
    k = int(round(((first_onset - fine) % beat) / step)) % steps_per_beat
    pick = k if score[k] >= 0.9 * score[best] else best
    phase = options[pick]
    while phase > first_onset + step / 2:                  # no note may fall before the first beat
        phase -= beat
    return phase


def fit_grid(onsets, bpm, offset=0.0, steps_per_beat=4, span=0.03):
    """Tune tempo and offset so that note onsets land on the step grid.

    A tempo that is half a percent off drifts by a whole sixteenth within a
    minute, which ruins quantisation while every single note is still "right".
    Onsets are much sharper evidence than the flux curve, so the estimate is
    polished on them: the best tempo is the one where the onsets' positions
    within a step agree most (largest mean resultant length).
    Returns ``(bpm, offset, agreement 0..1)``.
    """
    np = need_numpy()
    t = np.asarray(sorted(onsets), dtype=np.float64)
    if len(t) < 8:
        return bpm, offset, 0.0
    best = (-1.0, bpm, 0.0)
    candidates = np.arange(bpm * (1 - span), bpm * (1 + span), bpm * 0.0002) if span > 0 else [bpm]
    for cand in candidates:
        step = 60.0 / cand / steps_per_beat
        z = np.exp(2j * math.pi * (t / step)).mean()
        if abs(z) > best[0]:
            best = (float(abs(z)), float(cand), float(np.angle(z)))
    agreement, bpm, angle = best
    step = 60.0 / bpm / steps_per_beat
    fine = (angle / (2 * math.pi)) * step                  # where, within a step, the onsets sit
    beat = 60.0 / bpm
    k = round((offset - fine) / step)                      # keep the beat phase found from the flux
    offset = (fine + k * step) % beat
    if offset > beat / 2:
        offset -= beat                                     # "just before the first beat", not a beat late
    return bpm, offset, agreement
