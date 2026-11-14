# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Finding the sounds that are not notes.

Film and ambient music lean on a small stock of gestures that no note list can
hold: a pitch or a hiss that slides up before a cut (a *riser*), the same going
down (a *fall*), a sound played backwards that grows out of nothing and stops
dead (a *swell*), a thud with a long low tail (an *impact*).  A transcriber
either ignores them or shreds them into a spray of wrong notes.

``find_effects`` looks for them directly, in the same picture of the sound the
transcribers use:

sweeps    Look at the picture along a slant instead of along a level line.  A
          held note is only briefly on any slanted line, so it vanishes; a
          pitch that slides at that slant stays on it and remains.  Follow
          what remains, and if it travels far enough it is a slide.  A hiss
          has no line to follow, so for hisses the centre of the noise is
          watched instead.
swells    Some part of the sound grows for half a second or more and then is
          cut off within a tenth.  Ordinary notes do the opposite.
impacts   A broad burst of noise whose low end is still there a second later
          and fading.  A kick drum would be gone; a bass note would not come
          alone.

These are rules of thumb fitted to clean, synthetic effects.  They are a first
description of such sounds, not a reliable detector for real mixes.
"""
from __future__ import annotations

from . import analysis
from .transcribe import LOW, SHORT_N_FFT

DEEP = 31                                                   # MIDI pitch: below it is rumble
FLAT = 0.75
HISS_SHARE = 0.25
SLOPES = (2.5, 3.5, 5.0, 7.0, 10.0, 14.0, 20.0, 28.0)      # semitones per second, each tried up and down


def find_effects(spec, min_seconds=0.6, min_travel=5.0, kinds=("riser", "fall", "swell", "impact")):
    """Return ``[{"kind", "start", "end", "low", "high", "noise", "strength"}, ...]``, times in seconds.

    ``low`` and ``high`` are the ends of a sweep in (fractional) MIDI pitch: a
    riser goes from low to high, a fall from high to low.  For a swell or an
    impact both give the pitch where most of the sound is.  ``noise`` says
    whether it is a hiss rather than a tone.
    """
    np = spec.np
    raw = spec.raw.astype(np.float64)
    if raw.shape[0] < int(spec.fps):
        return []
    ref = float(np.percentile(raw.max(axis=1), 95))
    if ref <= 0:
        return []
    out = []
    if "riser" in kinds or "fall" in kinds:
        tone = _tone_sweeps(np, raw, ref, spec.fps, spec.bps, min_seconds, min_travel)
        hiss = _hiss_sweeps(np, raw, spec.fps, spec.bps, min_seconds, min_travel)
        for e in tone + hiss:                               # the same sweep seen twice (an overtone, or its hiss) is one
            twin = [o for o in out if o["kind"] == e["kind"] and min(o["end"], e["end"]) - max(o["start"], e["start"])
                    > 0.5 * min(o["end"] - o["start"], e["end"] - e["start"])]
            if twin:
                twin[0]["start"], twin[0]["end"] = min(twin[0]["start"], e["start"]), max(twin[0]["end"], e["end"])
            elif e["kind"] in kinds:
                out.append(e)
    if "swell" in kinds:
        sweeps = list(out)
        for s in _swells(np, raw, spec.fps, spec.bps):      # a sweep passing a pitch looks like a swell there
            if not any(e["start"] - 0.3 <= s["end"] <= e["end"] + 0.4 for e in sweeps):
                out.append(s)
    if "impact" in kinds:
        out += _impacts(np, spec, raw)
    for e in out:
        e.update(start=round(float(e["start"]), 3), end=round(float(e["end"]), 3), strength=float(e["strength"]))
    return sorted(out, key=lambda e: (e["start"], e["kind"]))


def _shifted(np, a, dt, db):
    """``a[t + dt, b + db]``, nothing where that falls outside."""
    out = np.zeros_like(a)
    T, B = a.shape
    t0, t1 = max(0, -dt), min(T, T - dt)
    b0, b1 = max(0, -db), min(B, B - db)
    if t1 > t0 and b1 > b0:
        out[t0:t1, b0:b1] = a[t0 + dt:t1 + dt, b0 + db:b1 + db]
    return out


def _along(np, raw, fps, bps, slope, share=0.2, looks=11):
    """What is still there when the picture is read along a slant of ``slope`` semitones a second."""
    half = min(0.6, max(0.12, 1.5 / abs(slope)))            # far enough to leave a held note behind
    w = max(2, int(round(half * fps)))
    taus = sorted(set(int(round(x)) for x in np.linspace(-w, w, looks)))
    stack = np.stack([_shifted(np, raw, tau, int(round(slope * bps * tau / fps))) for tau in taus])
    k = int(share * (len(taus) - 1))
    return np.partition(stack, k, axis=0)[k]


def _tone_sweeps(np, raw, ref, fps, bps, min_seconds, min_travel):
    frames, bins = raw.shape
    out = []
    up = [_along(np, raw, fps, bps, s) for s in SLOPES]
    down = [_along(np, raw, fps, bps, -s) for s in SLOPES]
    for sign, kind in ((1, "riser"), (-1, "fall")):
        best = np.zeros_like(raw)
        slope = np.zeros_like(raw)
        for i, s in enumerate(SLOPES):
            # a blob too wide to leave reads the same both ways; a slide reads one way only
            with_it, against = (up[i], down[i]) if sign > 0 else (down[i], up[i])
            line = np.maximum(0.0, with_it - 2.0 * against)
            better = line > best
            best[better] = line[better]
            slope[better] = sign * s
        tracks = []
        work = best.copy()
        for _ in range(12):
            t0, b0 = np.unravel_index(int(np.argmax(work)), work.shape)
            if work[t0, b0] < 0.12 * ref:
                break
            path = {t0: b0}
            for step in (1, -1):
                t, b, missed = t0, float(b0), 0
                rate = float(slope[t0, b0])                 # bins travelled are rate * bps / fps a frame
                while 0 <= t + step < frames and missed <= int(0.12 * fps):
                    t += step
                    b += step * rate * bps / fps
                    centre = int(round(b))
                    if centre < 2 or centre >= bins - 2:
                        break
                    lo, hi = centre - 2, centre + 3
                    j = lo + int(np.argmax(work[t, lo:hi]))
                    if work[t, j] >= 0.04 * ref:
                        b, missed = float(j), 0
                        rate = 0.5 * rate + 0.5 * float(slope[t, j])
                        path[t] = j
                    else:
                        missed += 1
            ts = sorted(path)
            for t in ts:                                    # used up: this line and its near neighbours
                work[t, max(0, path[t] - 2 * bps):path[t] + 2 * bps + 1] = 0.0
            a, z = ts[0], ts[-1]
            travel = sign * (path[z] - path[a]) / float(bps)
            if (z - a + 1) / fps < min_seconds or travel < min_travel or len(ts) < 0.7 * (z - a + 1):
                continue
            span = max(2, int(round(0.25 * fps)))           # it has to keep moving, not arrive in jumps
            pairs = [(path[t + span] - path[t]) * sign for t in ts if t + span in path]
            onward = sum(1 for d in pairs if d >= 0.25 * 1.5 * bps) / float(max(1, len(pairs)))
            strong = float(np.median([best[t, path[t]] for t in ts]))
            if onward >= 0.85 and strong >= 0.08 * ref and _stuck(np, raw, path, ts, bps) <= 0.45:
                tracks.append((a, z, path))
        tracks.sort(key=lambda k: k[2][k[0]])                # lowest first: the fundamental before its overtones
        kept = []
        for a, z, path in tracks:                           # an overtone runs beside its fundamental: one sweep
            shadow = False
            for a2, z2, path2 in kept:
                both = [t for t in path if t in path2]
                if len(both) >= 0.5 * min(len(path), len(path2)):
                    gap = np.median([abs(path[t] - path2[t]) for t in both]) / float(bps)
                    if min(abs(gap - h) for h in (12.0, 19.0, 24.0, 28.0, 31.0)) < 1.2:
                        shadow = True
            if shadow:
                continue
            kept.append((a, z, path))
            ends = sorted((LOW - 1 + path[a] / float(bps), LOW - 1 + path[z] / float(bps)))
            out.append({"kind": kind, "start": a / fps, "end": (z + 1) / fps, "low": round(ends[0], 1),
                        "high": round(ends[1], 1), "noise": False,
                        "strength": round(min(1.5, max(best[t, path[t]] for t in path) / ref * 2), 2)})
    return out


def _stuck(np, raw, path, ts, bps):
    """How much of the way the loudest point near the path stood still: notes do, a slide does not."""
    where = []
    for t in ts:
        lo, hi = max(1, path[t] - bps), min(raw.shape[1] - 1, path[t] + bps + 1)
        j = lo + int(np.argmax(raw[t, lo:hi]))
        a, b, c = raw[t, j - 1], raw[t, j], raw[t, j + 1]
        bend = a - 2 * b + c
        where.append(j + (0.5 * (a - c) / bend if bend < 0 else 0.0))
    moves = np.abs(np.diff(where)) / np.maximum(1, np.diff(ts))
    usual = abs(where[-1] - where[0]) / float(max(1, ts[-1] - ts[0]))
    return float((moves < 0.25 * usual).mean()) if len(moves) and usual > 0 else 1.0


def _hiss_sweeps(np, raw, fps, bps, min_seconds, min_travel):
    """A band of noise that travels: watch the centre of whatever hiss is new."""
    frames, bins = raw.shape
    every = max(1, int(round(fps / 11.0)))
    n = frames // every
    if n < 8:
        return []
    slow = raw[:n * every].reshape(n, every, bins).mean(axis=1)
    f = fps / every
    def lasting(a):                                         # what is there for a third of a second: not a drum
        return np.minimum(np.minimum(_shifted(np, a, -2, 0), _shifted(np, a, -1, 0)),
                          np.minimum(a, _shifted(np, a, 1, 0)))

    hiss = lasting(analysis.median_filter(np, slow, (8 * bps) | 1, 1))          # no peaks: what lies between them
    moving = np.maximum(0.0, hiss - analysis.median_filter(np, hiss, int(2.0 * f) | 1, 0))
    total = moving.sum(axis=1)
    held = lasting(slow).sum(axis=1)
    floor = 0.25 * float(np.percentile(hiss.sum(axis=1), 95))
    alive = (total > max(floor, 1e-9)) & (total > HISS_SHARE * held)
    centre = (moving * np.arange(bins)).sum(axis=1) / np.maximum(total, 1e-12) / bps + (LOW - 1)
    out = []
    t = 0
    while t < n:
        if not alive[t]:
            t += 1
            continue
        z = t
        while z + 1 < n and alive[z + 1]:
            z += 1
        if (z - t + 1) / f >= max(min_seconds, 0.9):
            c = centre[t:z + 1]
            x = np.arange(len(c)) / f
            fit = np.polyfit(x, c, 1)
            travel = fit[0] * x[-1]
            steps = np.diff(c)
            same = float((np.sign(steps) == np.sign(fit[0])).mean()) if len(steps) else 0.0
            if abs(travel) >= min_travel and same >= 0.75:
                ends = sorted((float(fit[1]), float(fit[1] + travel)))
                out.append({"kind": "riser" if travel > 0 else "fall", "start": t * every / fps,
                            "end": (z + 1) * every / fps, "low": round(ends[0], 1), "high": round(ends[1], 1),
                            "noise": True, "strength": round(min(1.5, float(total[t:z + 1].max()) / floor / 4), 2)})
        t = z + 1
    return out


def _swells(np, raw, fps, bps):
    """Sound that grows and is then cut: the mirror image of a struck note."""
    frames, bins = raw.shape
    k = np.ones(3) / 3.0
    soft = np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), 0, raw)
    soft = (soft + _shifted(np, soft, 0, 1) + _shifted(np, soft, 0, -1)) / 3.0

    def ago(seconds):
        return _shifted(np, soft, -int(round(seconds * fps)), 0)

    cut = _shifted(np, soft, int(round(0.15 * fps)), 0)
    steps = [soft] + [ago(0.1 * i) for i in range(1, 6)]
    grew = (cut < 0.3 * soft) & (steps[1] < 0.95 * soft) & (steps[3] < 0.65 * soft) & (steps[5] < 0.45 * soft) \
        & (steps[3] > 0.04 * soft)
    for later, earlier in zip(steps, steps[1:]):            # no step back on the way up
        grew &= earlier <= 1.1 * later
    score = (soft * grew).sum(axis=1)
    whole = soft.sum(axis=1)
    ref = float(np.percentile(whole, 95)) or 1.0
    out = []
    for t in analysis.peaks(np, score / ref, 0.2):
        t = int(t)
        near = slice(max(0, t - 2), min(frames, t + 3))
        which = grew[near].any(axis=0)
        band = soft[:, which].sum(axis=1)
        s = t
        while s > 0 and t - s < 10 * fps and 0.08 * band[t] < band[s - 1] <= 1.15 * band[s]:
            s -= 1
        if (t - s) / fps < 0.4:
            continue
        shape = soft[t] * which
        where = float((shape * np.arange(bins)).sum() / max(shape.sum(), 1e-12)) / bps + (LOW - 1)
        wide = int(which.sum()) / float(bps)                # semitones of the picture that took part
        out.append({"kind": "swell", "start": s / fps, "end": (t + 2) / fps, "low": round(where, 1),
                    "high": round(where, 1), "noise": bool(wide > 30), "strength": round(min(1.5, score[t] / ref * 2), 2)})
    kept = []
    for e in out:
        if not kept or e["end"] - kept[-1]["end"] > 0.3:
            kept.append(e)
    return kept


def _impacts(np, spec, raw):
    short = spec.short
    frames, bins = short.shape
    bin_hz = spec.rate / float(SHORT_N_FFT)
    mid = slice(int(700 / bin_hz), min(bins, int(4500 / bin_hz) + 1))
    deep = raw[:, :max(1, (DEEP - LOW + 1) * spec.bps)].sum(axis=1)        # what sounds below about 50 Hz
    ref = float(np.percentile(raw.sum(axis=1), 95)) or 1.0
    fps, sfps = spec.fps, spec.flux_fps

    def at(seconds):
        return float(deep[min(len(deep) - 1, max(0, int(round(seconds * fps))))])

    found = []
    for pf in analysis.peaks(np, spec.flux, 0.3):
        pf = int(pf)
        if pf < 3 or pf + 3 >= frames:
            continue
        t = pf / sfps
        before = short[pf - 3:pf - 1].mean(axis=0)
        rise = np.maximum(0.0, short[pf:pf + 3].max(axis=0) - before)
        flat = float(np.median(rise[mid]) / max(float(np.mean(rise[mid])), 1e-9))       # near 0.9 for noise
        base = at(t - 0.5)
        gain = at(t + 0.5) - base
        if flat > FLAT and gain > 0.06 * ref and at(t + 1.7) - base < 0.6 * gain:
            end = t + 0.5
            while end < t + 4.0 and at(end) - base > 0.25 * gain:
                end += 0.1
            thump = float(short[pf:pf + 4, 1:6].sum(axis=1).max() - before[1:6].sum())
            found.append({"kind": "impact", "start": t, "end": end, "low": 33.0, "high": 33.0,
                          "noise": False, "strength": round(min(1.5, gain / ref * 4), 2), "_thump": thump})
    # the deep end is seen through a long window, so a hit just before the real one qualifies too: keep the thump
    found = [e for e in found if not any(o is not e and abs(o["start"] - e["start"]) < 0.8
                                         and o["_thump"] > e["_thump"] for o in found)]
    lows = short[:, 1:6].sum(axis=1)
    for e in found:                                         # and put the start where the low end actually jumps
        del e["_thump"]
        a = int(e["start"] * sfps)
        z = min(frames - 4, a + int(0.8 * sfps))
        if z > a:
            jump = [float(lows[i + 1:i + 4].max() - lows[max(0, i - 2):i].mean()) if i >= 1 else 0.0 for i in range(a, z)]
            e["start"] = (a + int(np.argmax(jump))) / sfps
            e["end"] = max(e["end"], e["start"] + 0.5)
    # an impact comes alone; several in a row are a drum and a bass playing together
    return [e for e in found if sum(1 for o in found if abs(o["start"] - e["start"]) < 4.0) <= 2]
