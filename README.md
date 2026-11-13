# eigenchip

**Reducing music to a few chip voices.**

A piece of music may have dozens of notes sounding at once. A simple chip synthesizer has
three or four voices, each playing one note at a time. *eigenchip* is a research toolkit
for the step in between: deciding which notes matter, and comparing different ways of
deciding.

Daniel Sandner ([ORCID 0000-0002-1041-814X](https://orcid.org/0000-0002-1041-814X)) ·
[eigensoundlab](https://github.com/eigensoundlab)

Status: early (0.1.0). It reads MIDI, has three arrangement strategies, writes songs for
the [CLIo](https://github.com/eryxgames/CLIo) game engine, and scores the results on a
small corpus. Python 3.8+, no dependencies.

## Try it

```
python -m eigenchip info    corpus/ode_to_joy.mid
python -m eigenchip compare corpus/crossing.mid --melody 0 --bass 2
python -m eigenchip convert corpus/ode_to_joy.mid -o ode.json --name ode
```

`convert` writes a CLIo song; with `--name` it is wrapped ready to paste into a game's
`music.json`. To hear a result, point `render` at a CLIo checkout, which supplies the
synthesizer:

```
python -m eigenchip render ode.json ode.wav --clio /path/to/CLIo
```

## How it is put together

```
 reader            quantize           arranger                writer
.mid  ──▶  Score  ────────▶  Grid  ────────────▶  Arrangement  ────▶  CLIo song (JSON)
           notes in          notes in             lead, bass, inner
           beats             steps                or chords, drums
                               │                       │
                               └──────  metrics  ──────┘
                                  what survived?
```

Each stage has one job and a plain data structure on either side (`eigenchip/ir.py`), so
any stage can be replaced without touching the others. The arrangers are the research;
everything else exists to feed them and to judge them.

| Arranger | Idea |
| --- | --- |
| `skyline` | Pitch only: the top line is the lead, the bottom line the bass, then the top of what is left. |
| `roles` | Work out which *channel* carries the melody and which the bass from simple statistics, and take the lead only from the lead channel. |
| `roles-arp` | As `roles`, but everything that is not lead or bass becomes one chord per half bar, played as an arpeggio. |

## What has been found so far

Scores for every arranger on every piece are in **[RESULTS.md](RESULTS.md)**, regenerated
by `python experiments/run.py`. Dated notes are in
[docs/research-log.md](docs/research-log.md). In brief:

- Neither way of finding the melody is safe. `skyline` loses it when anything sits above
  the tune; `roles` loses it to a busy broken-chord accompaniment. No strategy here gets
  both cases right, which makes that the first problem to solve.
- Turning the accompaniment into arpeggiated chords keeps more of the harmony than a
  third melodic line, at some cost to the accompaniment's rhythm.
- Three-note chords are a hard ceiling for dense harmony.

## What the scores mean, and what they do not

The measures compare notes with notes (`eigenchip/metrics.py`): is the melody in the lead
voice, is the bass in the bass voice, how much pitch content was kept, how much was
invented, does each beat have the same harmony, do notes start where they started.

They do not listen. A high score means the right pitches are present at the right time; it
does not mean the result sounds good. Two limits to keep in mind:

- Scores are taken against the source *after* it has been snapped to the grid, so damage
  done by the grid itself (triplets, swing) is reported separately and not scored.
- The corpus is nine short pieces, mostly written to break things. It shows how methods
  fail; it does not show how they perform on real repertoire.

## The corpus

`corpus/build.py` writes every piece from note lists, so the answers (which channel is
the melody, which is the bass) are known exactly and the files can be rebuilt bit for
bit. The tunes are in the public domain or were written for this project. To add a piece,
add a function there and run it; please use only material that is public domain or your
own.

## Adding an arranger

Create `eigenchip/arrangers/yours.py` with `NAME`, `SUMMARY` and
`arrange(grid, voices=3) -> Arrangement`, and list it in `eigenchip/arrangers/__init__.py`.
It then appears in `convert --arranger`, in `compare` and as a new row in the results.
Run `python experiments/run.py` and read the diff of `RESULTS.md`: that diff is the
experiment.

## Directions

- **Finding the melody**: a detector that survives both a pad above the tune and a busy
  accompaniment below it.
- **Harmony**: four-note chord voices; chord windows that follow the harmonic rhythm;
  recognising an arpeggio in the source and storing it as a chord.
- **Structure**: finding repeated passages that are not aligned to four-bar blocks.
- **Timbre**: choosing waveform and envelope from the source instrument.
- **Rhythm**: grids for triplets and swing; a measure taken against the unquantised source.
- **More readers**: tracker modules; pitch tracking for a solo recording; a transcription
  model for mixed audio. These would be optional extras, leaving the core dependency-free.
- **Style, not copy**: extract only key, tempo and chords, and have a generative composer
  write new music from them.
- **Listening**: a protocol for judging results by ear, to find out which of the symbolic
  measures agree with listeners.

## Tests

```
python -m unittest discover -s tests
```

Set `CLIO_HOME` to a CLIo checkout to also check that every converted song plays in the
real synthesizer.

## Citing

See [CITATION.cff](CITATION.cff). A DOI will be added when a release is archived.

## Licence

[Apache-2.0](LICENSE). Copyright 2026 Daniel Sandner.
