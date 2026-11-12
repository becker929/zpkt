# The HW002 arranger

A phone page for trying arrangements of HW002 out of loops bounced from Live.

1. `uv run --project hands python contrib/arranger/bounce.py` solos each part of the set in Live and exports Main
   (15 bounces, about 6 minutes). Live must have the working copy `HW002_121_pp_loops` in front.
2. `uv run --project hands python contrib/arranger/mine.py` cuts those bounces into loops and one-shots on the bar,
   writes `loops.json`, and checks the song's own arrangement, summed, against Live's bounce of the mix.
3. `python3 contrib/arranger/server.py` serves the page on 127.0.0.1:8975; `tailscale serve` puts it on the tailnet.

The audio and the saved arrangements stay outside the repo (`~/_agent_scratch/arranger`).

The page starts the loops together on the bar clock and does nothing else to them. That is the one named exception
to the sound rule (`contrib/docs/sound.md`): it is a sketch, and an arrangement that matters is rendered in Live.
Each saved arrangement names its loops by stem and source bar, so it can be rebuilt in the set.
