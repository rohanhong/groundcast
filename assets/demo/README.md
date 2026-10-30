# Demo recordings

## `olm-session-light.gif`, `olm-session-dark.gif`

Silent recordings of the app, shown in the README: fetch a web page, fill in
a brief, start a two-host session, then play it with the transcript following
along and open the source of the sentence being read. The README shows the
dark one to readers whose GitHub theme is dark and the light one otherwise.

- Both were recorded on 2026-10-30, each from a fresh data directory, with
  the default settings (Claude Code as the LLM backend, Kokoro voices), the
  app following the browser's light or dark scheme, and the same brief:
  "How the olm survives in its caves: finding food in total darkness, its
  slow metabolism, and its long life", 4 minutes, Commute, Two hosts,
  Introductory.
- They are two separate runs, so their scripts differ. Everything on screen
  is real output of its run.
- Edits: the wait while the session was written, checked, and voiced (3
  minutes 48 seconds for the light run, 3 minutes 30 seconds for the dark
  run) is replaced by a title card, and each recording runs 1.3 times faster
  than real time. A drawn cursor stands in for the mouse, and the source page
  opened in the same tab instead of a new one.
- 1280 x 760 pixels, 15 frames per second, about 40 to 45 seconds.

### Licence

The material is the Wikipedia article "Olm"
(https://en.wikipedia.org/wiki/Olm) by Wikipedia contributors, under the
Creative Commons Attribution-ShareAlike 4.0 licence
(https://creativecommons.org/licenses/by-sa/4.0/). The recordings show text
from that article and scripts based on it, so they are shared under the
same licence, unlike the rest of the repository.

### Re-recording

The interface changes over time, and these recordings do not. Replace both
when the screens they show change visibly: from the repository root, with
`pip install playwright pillow` and Google Chrome,

```
python scripts/record_demo.py run assets/demo/olm-session.toml --scheme light
python scripts/record_demo.py run assets/demo/olm-session.toml --scheme dark
```

Each run starts its own service on a free port with an empty data
directory, calls the configured LLM backend for one session, and writes the
GIF named in `olm-session.toml`, which also holds the material, the brief,
the card text, and the timing. Pass `--font` with the Fraunces variable
font for the card, and `--frames DIR` to keep the frames, so that
`record_demo.py gif` can compose the GIF again (for example at another
speed) without a new session. Use material that is openly licensed or
self-written (see AGENTS.md), and update this file and the caption in
`README.md` and its translations.
