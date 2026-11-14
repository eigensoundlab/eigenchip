#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Convert recordings of your own and compare each chip version with its original, sound against sound.

    python experiments/listen.py piece.wav another.ogg [--seconds 60] [--transcriber nmf]

There are no true notes for a recording, so the note scores of ``RESULTS.md``
cannot be had.  What can be measured is how alike the two sounds are (see
``eigenchip/audio/compare.py``): harmony, bass, loudness and movement, each
from 0 (two unrelated sounds) to 1.  The table shows what each setting buys.
Nothing is written to the repository; recordings stay where they are.
"""
import argparse
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from eigenchip.arrangers import arrange                        # noqa: E402
from eigenchip.audio import compare, decode                    # noqa: E402
from eigenchip.ir import quantize                              # noqa: E402
from eigenchip.readers.audio import score_from_samples         # noqa: E402
from eigenchip.writers import clio                             # noqa: E402

SETTINGS = [("3 voices, plain, notes only (as 0.5.0)", 3, {"expression": "plain", "effects": False}),
            ("3 voices, plain", 3, {"expression": "plain"}),
            ("3 voices, full", 3, {}),
            ("4 voices, full", 4, {}),
            ("5 voices, full", 5, {}),
            ("6 voices, full", 6, {})]


def clio_synth():
    spec = importlib.util.spec_from_file_location("clio_synth", os.path.join(ROOT, "web", "vendor", "clio", "clio_synth.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def listen(path, seconds=60.0, transcriber="nmf", arranger="roles-arp", synth=None):
    """Rows ``(setting, likeness dict, voices)`` for one recording."""
    import numpy as np
    synth = synth or clio_synth()
    samples, rate, _info = decode.load(path)
    samples = samples[:int(seconds * rate)]
    score = score_from_samples(samples, rate, transcriber=transcriber)
    grid = quantize(score)
    rows = []
    for label, voices, options in SETTINGS:
        arr = arrange(grid, arranger, voices)
        song = clio.to_song(arr, grid, **options)
        chip = np.asarray(synth.render_song(song), dtype=np.float32)
        if synth.RATE != rate:
            chip = decode.resample(chip, synth.RATE, rate)
        rows.append((label, compare.compare(samples, chip, rate, score.info.get("offset", 0.0)), len(arr.voices)))
    return score, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--seconds", type=float, default=60.0, help="how much of each file to convert (default 60)")
    ap.add_argument("--transcriber", default="nmf")
    ap.add_argument("--arranger", default="roles-arp")
    args = ap.parse_args(argv)
    synth = clio_synth()
    for path in args.files:
        score, rows = listen(path, args.seconds, args.transcriber, args.arranger, synth)
        info = score.info
        print("\n%s: %d notes, %d drum hits, %d effects, %.0f%% lasting noise, %.1f attacks a second\n" % (
            os.path.basename(path), sum(1 for n in score.notes if not n.drum), info.get("drum_hits", 0),
            len(info.get("effects", [])), 100 * info.get("noise_share", 0.0), info.get("attacks_per_second", 0.0)))
        print("| setting | harmony | bass | loudness | movement |\n| --- | ---: | ---: | ---: | ---: |")
        for label, like, _voices in rows:
            print("| %s | %s |" % (label, " | ".join("%.2f" % like[k] for k in compare.KEYS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
