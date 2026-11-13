# Changelog

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
