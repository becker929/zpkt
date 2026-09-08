# Stage 5: asking producers for stems

## What we searched first

Before asking anyone, we looked for stems already under a free licence.
archive.org holds about 190 items tagged "stems" with a Creative Commons
licence from 2018 on. None is hard techno. The nearest by title is one Jamendo
mirror, "WOLK – Hope (Techno Stems Track)" (CC BY-NC-SA 3.0, 2020); its
metadata says deep house and the item holds one mixed mp3, no stems. The Cambridge Music Technology
multitrack library is education-only and has no hard techno either. So real
stems have to come from producers.

## Who to ask

The free-licence labels in the corpus, in order of how many of their tracks
we measured. Each has a contact page or email on its archive.org or
Bandcamp presence; the corpus manifest (`corpus2/manifest.json`) lists the
`page_url` per track.

1. Sascha Müller / SSREXTRA (self-released, CC BY-NC-ND)
2. Inquieto / InquietoMusik, Physical Techno Recordings
3. Dancefloor Socialism (THE D3VI7 and the Netlabel Day compilations)
4. Fresscode Records
5. Psychocandies
6. USER Records
7. BlackVogue Records
8. Dark Night Productions, Solar Fighter, NUKE THE PLANET (self-released)

## The ask (copy, fill the brackets, send)

Subject: your stems, for a small open study of hard techno sounds

Hi [name],

I run a small open research project on what makes a sound do its job in
hard techno: why one sound reads as the kick, another as the rumble, and so
on. Everything is published in plain language at
https://anthonybecker.me/research/sound-function/ and all code and numbers
are public.

So far the single-sound measurements are on synthetic sounds. Real stems
would let me check them against real ones. I already measured [track] from
[release] under its CC licence, with credit.

Would you share the stems (or just the kick, rumble, hat and clap channels)
of one or two tracks? I would:

- keep the audio private and never redistribute it,
- publish only measurements (numbers and plots), with credit to you,
- send you the results before they go up, and take them down if you ask.

If you would rather not, no problem at all, and thank you for releasing
your music under a licence that made the study possible.

[your name]

## What to do when stems arrive

Drop each stem into `library/real/stems/<producer>/<track>/<stem>.wav`,
label each with one of the ten roles in `library/real/manifest.csv`, then
re-run `analysis/classify.py` with the real CSV. The classifier's
synth-to-real accuracy is the number that changes.
