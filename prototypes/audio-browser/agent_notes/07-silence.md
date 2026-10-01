# 07 — Skipping silence

A quarter of the remaining collection is dead air. Of 45.8 hours, 11.5 hours sit
below −50 dB. Most of it is leading and trailing silence on stems and takes, and
long empty stretches inside project bounces.

Two consequences follow. The player should not make anyone sit through it, and
the statistics should stop counting it as listening time.

## Measurement, already done

`ffmpeg` with `silencedetect=n=-50dB:d=0.4` over every non-discarded sound. Two
tables exist, written by direct SQL rather than a migration:

```sql
silence          (hash PK, max_db, mean_db, silent_s, duration_s,
                  silent_frac, measured_at)
silence_interval (hash, start_s, end_s, PRIMARY KEY (hash, start_s))
```

6,604 intervals over 942 sounds. Fold both into `schema.sql` as
`CREATE TABLE IF NOT EXISTS` so a fresh index has them, and add a CLI command
that measures sounds lacking rows, so this is reproducible rather than a
one-off.

## The 2 second floor

The minimum gap worth skipping is **2.0 seconds**, and the choice barely costs
anything:

| Minimum gap | Sounding time | Saved |
|---|---|---|
| 0.4 s | 34.3 h | 11.5 h |
| 1.0 s | 35.0 h | 10.8 h |
| 2.0 s | 35.4 h | 10.4 h |
| 5.0 s | 35.8 h | 10.0 h |

Nearly all the silence is in long stretches, so a 2 second floor recovers 10.4
of the 11.5 available hours while never skipping a musical rest or the gap
between two hits. Skipping at 0.4 s would jitter for 1.1 hours more.

Store every interval down to 0.4 s and filter at read time. The floor is then a
setting rather than a property of the data.

## Sounding duration

**Sounding duration** is wall duration minus silence of 2.0 seconds or more. It
is what the interface shows everywhere a length is shown: list rows, the detail
view, playlist totals, and the collection header.

Wall duration stays available and is shown alongside when the two differ by more
than a few seconds. A sound that is 5 minutes long but 40 seconds of sound
should say so, because that difference is itself informative — it usually means
a stem that barely plays.

`/api/stats` and `/api/triage` report sounding time. The header currently says
75.6 h across the whole index; it should say sounding hours.

## Routes

| Route | Purpose |
|---|---|
| `GET /api/files/{hash}/silence` | Intervals and `sounding_s`. Takes `?min_gap=` defaulting to 2.0. |

`FileSummary` and `FileDetail` gain `sounding_s`. `GET /api/files` gains
`?sort=sounding`.

## Player behaviour

Auto-skip is **on by default**, with a toggle that persists.

When playback enters an interval of 2 seconds or more, seek to its end. Skip
leading silence on load, and treat trailing silence as the end of the track so
the queue advances instead of playing out dead air.

Show it. Tint silent regions on the waveform, and let a manual seek into a
silent region stay there — an explicit scrub must not be fought by the skipper.

**Transcoded AIF cannot seek.** Those responses carry `Accept-Ranges: none`, and
about 1,180 paths are AIF. Auto-skip cannot work on them. Say so where the
existing unseekable affordance already appears rather than silently doing
nothing.

## Constraints

- No route may delete audio. The two tests asserting this must keep passing.
- Skipping changes playback only. It never rewrites a file.
- Keep hydration clean; the phone suite fails on any console error.

## Navigation

- **up**: [00-index.md](00-index.md)
- **back**: [05-triage.md](05-triage.md)
- **next**: none.
