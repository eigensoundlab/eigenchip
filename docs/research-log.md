# Research log

Dated notes on what was tried and what it showed. Newest first. Keep entries short; the
numbers live in `RESULTS.md` and in the history of that file.

## 2026-11-13 - baseline: three arrangers, nine pieces

**Set-up.** `skyline`, `roles`, `roles-arp` at three voices on a sixteenth-note grid,
scored against the quantised source.

**What the table shows.**

- *Neither lead detector is safe.* `skyline` loses the melody completely when a pad sits
  above it (`crossing`). `roles` gets that right but loses the melody completely on
  `twinkle`, where it mistakes the Alberti bass for the tune: a broken chord is
  monophonic, busy and always moving, which is exactly what the heuristic rewards.
- *Arpeggiated chords keep the most.* `roles-arp` retains at least as much of the
  original pitch content as a third melodic line on every piece, and clearly more
  wherever the harmony is thicker than three voices. The cost is in rhythm (the
  accompaniment's own rhythm is replaced by the arpeggio) and in precision (a chord held
  for half a bar sounds notes longer than the source did); both are most visible on
  `waltz` and `frere_jacques`.
- *Three notes per chord is a ceiling.* On `dense_chords` even `roles-arp` keeps under
  two thirds of the pitch content.
- *A round has no single melody.* On `frere_jacques` every method fails the melody
  measure; the measure itself is questionable there.

**What the table cannot show.**

- Damage done by the grid. Scores compare against the *quantised* source, so `triplets`
  scores perfectly although its rhythm has been bent. The quantisation error is reported
  beside each piece but is not part of any score.
- Whether any of it sounds good. Nothing here has been judged by ear.

**Next.**

1. A lead detector that passes both `crossing` and `twinkle` (penalise cyclic,
   low-entropy figures; reward stepwise motion and phrase structure).
2. A measure that compares against the unquantised source.
3. Chord voices of four notes, and chord windows that follow the harmonic rhythm
   instead of a fixed half bar.
