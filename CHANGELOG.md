# Changelog

## 0.3.0 - 2026-11-13

A workbench in the browser.

- `web/`: a static page that runs the package unchanged in the browser (Python through
  Pyodide, in a worker). Open a MIDI or sound file, or take a corpus piece as written or
  played by the test synthesizer; see the notes that were found against the voices the
  chip plays; switch between the original and the chip version while it plays; compare
  the arrangers in a table and switch by choosing a row; download the CLIo song, the
  transcription as MIDI and the chip sound. Files are not uploaded anywhere.
- The chip sound comes from CLIo's own synthesizer, vendored at tag `v2.0.0`.
- `eigenchip.app.Session`: the same steps as a small Python API returning plain data.
- Serving: GitHub Pages from the repository root (`index.html` forwards to `web/`).

## 0.2.0 - 2026-11-13

Audio in: sound files can be read, by transcribing them.

- Decoding: WAV (8/16/24/32-bit PCM, 32/64-bit float, extensible) with the standard
  library and NumPy; Ogg, Opus, MP3, FLAC, M4A/AAC, AIFF and others through ffmpeg.
- Analysis: spectrogram, harmonic-percussive separation, onset strength, tempo by
  autocorrelation, and a fit of tempo and first beat to the transcribed onsets.
- Three transcription baselines behind one interface: `mono` (predominant pitch on a
  smoothed path), `peaks` (harmonic summation with cancellation), `nmf` (fixed harmonic
  templates). One shared routine cuts activations into notes and detects repeated notes.
- A reference synthesizer that plays the corpus in several tone colours, so that the
  audio has known answers; note-level and frame-level transcription scores.
- `experiments/audio.py` writes `RESULTS-audio.md`: transcribers by tone colour, the
  effect of drums and of lossy compression, tempo, and the whole chain from audio to
  arrangement against the same arrangement from MIDI.
- Command line: `transcribe` (sound file to MIDI); `convert`, `compare` and `info` accept
  sound files, with `--transcriber`, `--tempo`, `--offset` and `--meter`.
- NumPy is needed for audio only (`pip install eigenchip[audio]`); the MIDI path still
  has no dependencies.

## 0.1.0 - 2026-11-13

First version: the frame that later experiments hang on.

- A common note model: `Score` (as read), `Grid` (snapped to steps), `Arrangement` (a few
  monophonic voices, a chord voice and drums).
- A Standard MIDI File reader and writer using only the standard library.
- Three arrangers: `skyline` (pitch only), `roles` (guess the melody and bass channels),
  `roles-arp` (roles, with everything else as arpeggiated chords).
- A writer for CLIo songs, with pattern detection.
- Symbolic measures of what survived: melody, bass, pitch content, harmony, rhythm.
- A nine-piece corpus with known answers, built from source.
- `experiments/run.py`, which scores every arranger on every piece into `RESULTS.md`.
- Command line: `info`, `convert`, `compare`, `render`.
