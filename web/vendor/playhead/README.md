# Playhead's analysis

`analysis.js` is `src/analysis.js` from [Playhead](https://github.com/eigensoundlab/playhead)
0.4.0 (commit `a0b6dda`), unchanged. It stands by itself (it sets `WL` on the page) and
needs nothing else of Playhead.

The page uses one thing of it: the tempo of what was hummed (`WL.analyse`, then
`WL.rhythmOf`), so that a tempo need not be set before humming. It is fetched only when
that is asked for, and the recording never leaves the page.

Copyright 2026 Daniel Sandner. Licensed under the Apache License, Version 2.0.

To update: copy the file from a newer Playhead and change the version named here.
