# CLIo's synthesizer

`clio_synth.py` is `engine/audio/synth.py` from [CLIo](https://github.com/eryxgames/CLIo)
as it will be in CLIo 2.3: tag `v2.2.1` plus the change that lets an instrument be
overdriven (`"drive": 0.6`), which the rock, metal, doom and industrial genres of `expand`
use for their guitars. Songs without `drive` sound exactly as they do in 2.2; a CLIo
without it plays a song that has `drive` with the same notes, clean. The web page uses
this file to play a song as the game engine would.

Copyright 2024-2026 Daniel Sandner. Licensed under the Apache License, Version 2.0.

To update: copy the file from a newer CLIo tag and change the tag named here and in
`web/index.html`.
