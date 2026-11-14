# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""How good is a transcription?  Compare its notes with the true ones.

Notes are ``(onset seconds, offset seconds, pitch)``.  A transcribed note is
correct when it has the right pitch and starts within ``tolerance`` of a true
note that no other transcribed note has claimed - the usual "note onset"
measure of the transcription literature (50 ms, offsets ignored).

precision  share of transcribed notes that are correct (few invented notes)
recall     share of true notes that were found (few missed notes)
f1         their harmonic mean
f1_class   the same with octaves forgiven: counts C3 for C4 as right, so the
           gap between f1 and f1_class is the amount of octave error
frame_f1   agreement on which pitches sound in each 20 ms slice (durations
           matter here, onsets do not)
"""
from __future__ import annotations


def _match(ref, est, tolerance, same):
    used = [False] * len(est)
    hits = 0
    for onset, _off, pitch in ref:
        best, best_d = None, tolerance
        for i, (e_on, _e_off, e_pitch) in enumerate(est):
            if used[i] or not same(pitch, e_pitch):
                continue
            d = abs(e_on - onset)
            if d <= best_d:
                best, best_d = i, d
        if best is not None:
            used[best] = True
            hits += 1
    return hits


def _prf(hits, n_ref, n_est):
    p = hits / float(n_est) if n_est else 0.0
    r = hits / float(n_ref) if n_ref else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def _frames(notes, step):
    out = set()
    for onset, offset, pitch in notes:
        a, b = int(round(onset / step)), max(int(round(onset / step)) + 1, int(round(offset / step)))
        for i in range(a, b):
            out.add((i, pitch))
    return out


def note_scores(ref, est, tolerance=0.05, frame=0.02):
    ref, est = sorted(ref), sorted(est)
    p, r, f = _prf(_match(ref, est, tolerance, lambda a, b: a == b), len(ref), len(est))
    _p, _r, fc = _prf(_match(ref, est, tolerance, lambda a, b: a % 12 == b % 12), len(ref), len(est))
    fr, fe = _frames(ref, frame), _frames(est, frame)
    _fp, _fr, ff = _prf(len(fr & fe), len(fr), len(fe))
    return {"precision": p, "recall": r, "f1": f, "f1_class": fc, "frame_f1": ff,
            "notes": len(est), "true_notes": len(ref)}


def drum_scores(ref, est, tolerance=0.05):
    """Compare drum hits ``[(seconds, "k" | "s" | "h"), ...]``. Precision, recall, F1 over all kinds."""
    hits = n_ref = n_est = 0
    for kind in "ksh":
        want = sorted(t for t, k in ref if k == kind)
        have = sorted(t for t, k in est if k == kind)
        used = [False] * len(have)
        for t in want:
            best, best_d = None, tolerance
            for i, x in enumerate(have):
                if not used[i] and abs(x - t) <= best_d:
                    best, best_d = i, abs(x - t)
            if best is not None:
                used[best] = True
                hits += 1
        n_ref += len(want)
        n_est += len(have)
    p, r, f = _prf(hits, n_ref, n_est)
    return {"precision": p, "recall": r, "f1": f, "hits": n_est, "true_hits": n_ref}


def effect_scores(ref, est):
    """Compare effects ``[{"kind", "start", "end", ...}, ...]`` (seconds) with the ones that were put in.

    A sweep or a swell counts as found when one of the same kind covers at
    least a third of it; an impact when one starts within 0.3 s.
    """
    used, by_kind = set(), {}
    for r in ref:
        row = by_kind.setdefault(r["kind"], {"true": 0, "found": 0})
        row["true"] += 1
        for i, e in enumerate(est):
            if i in used or e["kind"] != r["kind"]:
                continue
            if r["kind"] == "impact":
                ok = abs(e["start"] - r["start"]) <= 0.3
            else:
                ok = min(r["end"], e["end"]) - max(r["start"], e["start"]) >= (r["end"] - r["start"]) / 3.0
            if ok:
                used.add(i)
                row["found"] += 1
                break
    found = sum(row["found"] for row in by_kind.values())
    return {"true": len(ref), "found": found, "reported": len(est), "wrong": len(est) - found, "kinds": by_kind}


def tempo_verdict(estimated, true, tolerance=0.02):
    """'ok', 'double', 'half', 'triple', 'third' or 'wrong'."""
    for label, ratio in (("ok", 1.0), ("double", 2.0), ("half", 0.5), ("triple", 3.0), ("third", 1 / 3.0),
                         ("3:2", 1.5), ("2:3", 2 / 3.0)):
        if abs(estimated / (true * ratio) - 1.0) <= tolerance:
            return label
    return "wrong"
