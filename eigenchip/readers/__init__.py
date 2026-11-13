# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Readers turn a file into a Score. One reader per kind of source."""
from __future__ import annotations

import os

from ..midi import read_midi

READERS = {".mid": read_midi, ".midi": read_midi, ".smf": read_midi}


def read(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in READERS:
        raise ValueError("No reader for '%s' files yet. Supported: %s" % (ext, ", ".join(sorted(READERS))))
    score = READERS[ext](path)
    if not score.title:
        score.title = os.path.splitext(os.path.basename(path))[0]
    return score
