# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Command line.

    eigenchip info song.mid
    eigenchip convert song.mid -o song.json [--arranger roles-arp] [--name theme]
    eigenchip compare song.mid [--melody 0 --bass 2]
    eigenchip render song.json song.wav --clio /path/to/CLIo
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__, metrics
from .arrangers import ARRANGERS, DEFAULT, arrange
from .ir import pitch_name, quantize
from .readers import read
from .writers import clio


def _fmt(value):
    return "  -  " if value is None else "%.2f" % value


def cmd_info(args):
    score = read(args.input)
    grid = quantize(score, args.steps_per_beat)
    mean_poly, max_poly = metrics.polyphony(grid)
    print("%s" % (score.title or args.input))
    print("  tempo %.1f bpm, meter %d/%d, %d notes, %.1f beats" % (
        score.tempo, score.meter[0], score.meter[1], len(score.notes), score.length))
    print("  polyphony: mean %.1f, max %d    quantisation error: %.3f steps" % (mean_poly, max_poly, grid.error))
    for key in ("tempo_changes", "meter_changes"):
        if score.info.get(key):
            print("  note: %d %s ignored (one tempo and one meter are kept)" % (score.info[key], key.replace("_", " ")))
    from .arrangers.common import channel_stats
    from .arrangers.roles import pick_roles
    lead, bass, stats = pick_roles(grid)
    for ch, st in sorted(channel_stats(grid).items()):
        role = "lead?" if ch == lead else "bass?" if ch == bass else ""
        print("  ch %2d %-18s %4d notes  mean %-4s mono %.2f  %s" % (
            ch, (score.names.get(ch) or "")[:18], st["notes"], pitch_name(int(round(st["mean_pitch"]))),
            st["monophony"], role))
    if grid.drums:
        print("  drums: %d hits" % len(grid.drums))
    return 0


def cmd_convert(args):
    score = read(args.input)
    grid = quantize(score, args.steps_per_beat)
    arr = arrange(grid, args.arranger, args.voices)
    song = clio.to_song(arr, grid, args.bars_per_pattern, args.title)
    problems = clio.validate(song)
    if problems:
        print("internal error, the song is not valid:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    text = clio.dumps(song, args.name)
    if args.output in (None, "-"):
        sys.stdout.write(text)
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        seq = song["sequence"]
        print("%s -> %s  (%s, %d voices, %d patterns, %d unique)" % (
            args.input, args.output, arr.name, len(arr.voices), len(seq), len(set(seq))), file=sys.stderr)
    return 0


def cmd_compare(args):
    score = read(args.input)
    grid = quantize(score, args.steps_per_beat)
    truth = {}
    if args.melody is not None:
        truth["melody"] = args.melody
    if args.bass is not None:
        truth["bass"] = args.bass
    print("%-10s %s" % ("arranger", "  ".join("%-9s" % c[:9] for c in metrics.COLUMNS)))
    for name in ARRANGERS:
        arr = arrange(grid, name, args.voices)
        song = clio.to_song(arr, grid, args.bars_per_pattern)
        res = metrics.evaluate(grid, arr, song, truth)
        print("%-10s %s" % (name, "  ".join("%-9s" % _fmt(res[c]) for c in metrics.COLUMNS)))
    if not truth:
        print("(give --melody CH and --bass CH to score melody_recall and bass_recall)")
    return 0


def cmd_render(args):
    home = args.clio or os.environ.get("CLIO_HOME")
    if not home or not os.path.isdir(os.path.join(home, "engine", "audio")):
        print("Rendering uses CLIo's synthesizer. Point --clio (or CLIO_HOME) at a CLIo checkout.", file=sys.stderr)
        return 2
    sys.path.insert(0, home)
    from engine.audio import synth          # noqa: E402  (CLIo, not a dependency of this package)
    with open(args.input, "r", encoding="utf-8") as f:
        song = json.load(f)
    if "patterns" not in song and len(song) == 1:
        song = next(iter(song.values()))
    samples = synth.render_song(song)
    synth.write_wav(args.output, samples, repeat=max(1, args.loops))
    print("%s -> %s (%.1f s)" % (args.input, args.output, len(samples) * args.loops / float(synth.RATE)), file=sys.stderr)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="eigenchip", description="Reduce music to a few chip voices.")
    ap.add_argument("--version", action="version", version="eigenchip %s" % __version__)
    sub = ap.add_subparsers(dest="command")

    def common(p):
        p.add_argument("input")
        p.add_argument("--steps-per-beat", type=int, default=4, help="grid resolution (default 4 = sixteenths)")
        p.add_argument("--voices", type=int, default=3, choices=(1, 2, 3), help="pitched voices (default 3)")
        p.add_argument("--bars-per-pattern", type=int, default=4)

    p = sub.add_parser("info", help="describe a file and guess the roles of its channels")
    p.add_argument("input")
    p.add_argument("--steps-per-beat", type=int, default=4)
    p.set_defaults(fn=cmd_info)

    p = sub.add_parser("convert", help="convert to a CLIo song")
    common(p)
    p.add_argument("-o", "--output", help="output file (default: standard output)")
    p.add_argument("--arranger", default=DEFAULT, choices=sorted(ARRANGERS))
    p.add_argument("--name", help="wrap the song as {name: song} for pasting into music.json")
    p.add_argument("--title")
    p.set_defaults(fn=cmd_convert)

    p = sub.add_parser("compare", help="run every arranger and print the scores")
    common(p)
    p.add_argument("--melody", type=int, help="channel that holds the melody (for melody_recall)")
    p.add_argument("--bass", type=int, help="channel that holds the bass (for bass_recall)")
    p.set_defaults(fn=cmd_compare)

    p = sub.add_parser("render", help="render a converted song to WAV using CLIo's synthesizer")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--clio", help="path to a CLIo checkout (or set CLIO_HOME)")
    p.add_argument("--loops", type=int, default=1)
    p.set_defaults(fn=cmd_render)

    args = ap.parse_args(argv)
    if not getattr(args, "fn", None):
        ap.print_help()
        return 0
    try:
        return args.fn(args)
    except (OSError, ValueError) as e:
        print("eigenchip: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
