# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Readers turn a file into a Score. One reader per kind of source.

MIDI files are read exactly.  Sound files are *transcribed*, which is a guess:
see :mod:`eigenchip.readers.audio`.
"""
from __future__ import annotations

import os

from ..audio import EXTENSIONS as AUDIO_EXTENSIONS
from ..midi import read_midi

READERS = {".mid": read_midi, ".midi": read_midi, ".smf": read_midi}


def is_audio(path):
    return os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS


def read(path, **options):
    """Read any supported file. ``options`` (transcriber, tempo, offset, meter) apply to audio only."""
    ext = os.path.splitext(path)[1].lower()
    if ext in READERS:
        score = READERS[ext](path)
    elif ext in AUDIO_EXTENSIONS:
        from .audio import read_audio           # imported late: it needs NumPy, MIDI reading does not
        score = read_audio(path, **{k: v for k, v in options.items() if v is not None})
    else:
        raise ValueError("No reader for '%s' files. Supported: %s" % (
            ext or path, ", ".join(sorted(READERS) + sorted(AUDIO_EXTENSIONS))))
    if not score.title:
        score.title = os.path.splitext(os.path.basename(path))[0]
    return score
