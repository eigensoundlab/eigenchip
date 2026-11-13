# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Sound file -> mono samples.

WAV (8/16/24/32-bit PCM, 32/64-bit float, also the "extensible" variant) is
parsed here with nothing but the standard library and NumPy.  Every other
format - Ogg Vorbis, Opus, MP3, FLAC, AAC/M4A, AIFF... - is handed to
``ffmpeg``, which must be on the PATH (or named in ``EIGENCHIP_FFMPEG``).
There is no pure-Python decoder for those formats in the standard library,
and writing one is not what this project is about.
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess

from . import RATE, AudioError, need_numpy

_PCM, _FLOAT, _EXTENSIBLE = 1, 3, 0xFFFE


def read_wav(path):
    """Read a WAV file. Returns ``(samples[frames, channels] float32 in -1..1, rate)``."""
    np = need_numpy()
    with open(path, "rb") as f:
        blob = f.read()
    if len(blob) < 12 or blob[:4] not in (b"RIFF", b"RF64") or blob[8:12] != b"WAVE":
        raise AudioError("%s is not a WAV file" % os.path.basename(path))
    fmt = data = None
    pos = 12
    while pos + 8 <= len(blob):
        tag, size = blob[pos:pos + 4], struct.unpack("<I", blob[pos + 4:pos + 8])[0]
        body = blob[pos + 8:pos + 8 + size]
        if tag == b"fmt ":
            fmt = body
        elif tag == b"data":
            data = body                     # a truncated file simply yields fewer samples
            if fmt is not None:
                break
        pos += 8 + size + (size & 1)        # chunks are padded to an even length
    if fmt is None or data is None or len(fmt) < 16:
        raise AudioError("%s: no audio data found" % os.path.basename(path))
    kind, channels, rate, _bps, _align, bits = struct.unpack("<HHIIHH", fmt[:16])
    if kind == _EXTENSIBLE and len(fmt) >= 26:
        kind = struct.unpack("<H", fmt[24:26])[0]
    if channels < 1 or rate < 1:
        raise AudioError("%s: damaged header" % os.path.basename(path))
    width = bits // 8
    usable = len(data) - len(data) % (width * channels) if width else 0
    data = data[:usable]
    if kind == _PCM and bits == 8:
        x = (np.frombuffer(data, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif kind == _PCM and bits == 16:
        x = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
    elif kind == _PCM and bits == 24:
        b = np.frombuffer(data, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        v = np.where(v >= 1 << 23, v - (1 << 24), v)
        x = v.astype(np.float32) / float(1 << 23)
    elif kind == _PCM and bits == 32:
        x = (np.frombuffer(data, dtype="<i4").astype(np.float64) / float(1 << 31)).astype(np.float32)
    elif kind == _FLOAT and bits == 32:
        x = np.frombuffer(data, dtype="<f4").astype(np.float32)
    elif kind == _FLOAT and bits == 64:
        x = np.frombuffer(data, dtype="<f8").astype(np.float32)
    else:
        raise AudioError("%s: WAV encoding %d with %d bits is not supported here "
                         "(ffmpeg can convert it)" % (os.path.basename(path), kind, bits))
    return x.reshape(-1, channels), int(rate)


def write_wav(path, samples, rate=RATE):
    """Write mono or [frames, channels] float samples as 16-bit PCM."""
    np = need_numpy()
    x = np.asarray(samples, dtype=np.float64)
    channels = 1 if x.ndim == 1 else x.shape[1]
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).round().astype("<i2").tobytes()
    head = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, _PCM, channels,
                       int(rate), int(rate) * channels * 2, channels * 2, 16, b"data", len(pcm))
    with open(path, "wb") as f:
        f.write(head + pcm)


def resample(x, src, dst):
    """Change the sample rate of a mono signal (low-pass first when going down)."""
    np = need_numpy()
    if src == dst or len(x) == 0:
        return np.asarray(x, dtype=np.float32)
    x = np.asarray(x, dtype=np.float64)
    if dst < src:                                   # keep what the new rate can carry, drop the rest
        cutoff = 0.5 * dst / float(src) * 0.94
        taps = 95
        n = np.arange(taps) - (taps - 1) / 2.0
        kernel = 2 * cutoff * np.sinc(2 * cutoff * n) * np.hanning(taps)
        x = np.convolve(x, kernel / kernel.sum(), mode="same")
    count = int(round(len(x) * dst / float(src)))
    where = np.arange(count) * (src / float(dst))
    return np.interp(where, np.arange(len(x)), x).astype(np.float32)


def ffmpeg_path(env=None):
    env = os.environ if env is None else env
    return env.get("EIGENCHIP_FFMPEG") or shutil.which("ffmpeg")


def read_ffmpeg(path, rate=RATE, tool=None):
    """Decode anything ffmpeg understands to mono float samples at ``rate``."""
    np = need_numpy()
    tool = tool or ffmpeg_path()
    if not tool:
        raise AudioError("Reading %s files needs ffmpeg (https://ffmpeg.org) on the PATH. "
                         "Without it, convert the file to WAV first."
                         % (os.path.splitext(path)[1].lower() or "these"))
    if not os.path.isfile(path):
        raise AudioError("%s: no such file" % path)
    cmd = [tool, "-v", "error", "-nostdin", "-i", path, "-vn", "-ac", "1", "-ar", str(int(rate)),
           "-f", "f32le", "-"]
    try:
        done = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        raise AudioError("Could not run ffmpeg: %s" % e)
    if done.returncode != 0 or not done.stdout:
        why = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise AudioError("ffmpeg could not decode %s%s" % (os.path.basename(path),
                                                         (": " + why[-1]) if why else ""))
    return np.frombuffer(done.stdout[:len(done.stdout) // 4 * 4], dtype="<f4").astype(np.float32)


def load(path, rate=RATE):
    """Any supported sound file -> ``(mono float32 samples, rate, info)``."""
    np = need_numpy()
    ext = os.path.splitext(path)[1].lower()
    info = {"format": ext.lstrip(".") or "?", "decoder": "wav"}
    x = None
    if ext in (".wav", ".wave"):
        try:
            frames, src = read_wav(path)
        except AudioError:
            if not ffmpeg_path():
                raise
        else:
            info.update(channels=frames.shape[1], source_rate=src)
            x = resample(frames.mean(axis=1), src, rate)
    if x is None:
        x = read_ffmpeg(path, rate)
        info["decoder"] = "ffmpeg"
    if len(x) == 0:
        raise AudioError("%s holds no audio" % os.path.basename(path))
    info["seconds"] = len(x) / float(rate)
    return np.ascontiguousarray(x, dtype=np.float32), rate, info
