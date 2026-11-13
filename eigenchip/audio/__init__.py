# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Audio in: decode a sound file, find its tempo, and guess its notes.

This is the second front end of eigenchip.  MIDI already *is* notes; audio has
to be transcribed first, and transcription is the hard, lossy part.  The
modules here are deliberately simple, readable baselines to measure against:

``decode``      WAV with the standard library, everything else through ffmpeg
``analysis``    spectrogram, onset strength, tempo and beat phase
``transcribe``  three ways to turn a spectrogram into notes
``synth``       a small reference synthesizer: audio whose notes are known
``evaluate``    how close a transcription is to the truth

Everything except plain WAV decoding of metadata needs NumPy
(``pip install eigenchip[audio]``); the rest of eigenchip does not.
"""
from __future__ import annotations

EXTENSIONS = (".wav", ".wave", ".ogg", ".oga", ".opus", ".mp3", ".flac", ".m4a", ".aac",
              ".aif", ".aiff", ".wma", ".webm", ".mka")
RATE = 22050


class AudioError(ValueError):
    """The file cannot be read as audio, or a tool needed to read it is missing."""


def need_numpy():
    try:
        import numpy
    except ImportError:
        raise AudioError("Reading audio needs NumPy. Install it with: pip install numpy "
                         "(or: pip install eigenchip[audio])")
    return numpy
