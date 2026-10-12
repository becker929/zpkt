# Publishing

Practice renders go to Anthony first, then to /skrng as one batch. Publishing is public. Only our renders and
our own words go out: never the tutorial's audio, frames or transcript.

**Current upload policy (12 October 2026):** Anthony defers R2 uploads. Runs stop at "prepared, not
uploaded". Update this line, and only this line, when he changes it.

## Loudness

- **One common gain for the whole batch.** Every version of a batch gets the same gain and the same limiter
  ceiling, so their sections compare directly. Per-file normalisation moved run 1's perc bars 1 LU apart
  between A and B. `publish_prep.py prep` lands the loudest version on the target and keeps the others
  where they fall.
- **Target about −15 LUFS,** with the decoded MP3's true peak at −1.0 dBTP or below. Run 1 used −14 LUFS
  with a −2 dBFS limiter on an unmastered mix (PLR about 16.5 dB). That took about 7 dB off the clap peaks
  and moved the onset detector's kick bias from −2 ms to +13 ms. The limiter had reshaped the attack.
- **Glue instead of limiting.** When prep warns that the loudest peak goes more than 3 dB into the limiter:
  1. put Glue Compressor on Live's Main track in the practice set;
  2. re-render and re-measure;
  3. re-run prep.

  Or accept −16 LUFS. Never fix loudness with offline processing beyond the common gain and a light limiter.
- **Format.** MP3, 44.1 kHz, CBR 192 kbps, a 5 ms fade-in and a 0.5 s fade-out over the tail. The
  practice measures the MP3s with the same render specs plus a `delivery` block.

## The batch

Batches follow the batch-8 format:

- the intro is said once at the top, then each track is announced "Track N.";
- Track 1 is faithful to the tutorial, Track 2 is the method on new material;
- 3–5 tracks at most.

The intro says what the technique is and what each track plays, in plain words. Each track's notes say what
it plays and how it differs from the others, and end with the credit line:

> Tutorial: "TITLE" by CHANNEL, URL.

`refs` holds the same link. The announcements use `lib/record/batch_intro.py`'s voice and loudness;
`publish_prep.py` calls it.

**Batch number.** Take the next free `n` in the site checkout's `skrng/batches.json`. Skip any number that a
prepared but unpublished run has reserved: the `published` field of each line in `runs.jsonl` names it
(run 1 holds batch 9). Write your own reservation the same way:
`$S/run runlog.py set ID published "prepared: /skrng batch N reserved"`.

## entries.json

`publish_prep.py prep` writes `W/practice/publish/entries.json`:

| Key | Holds |
|---|---|
| `manifest_entries` | entries for `skrng/manifest.json` (newest first) |
| `batch` | the entry for `skrng/batches.json` |
| `uploads` | the upload map: a local file (relative to entries.json), its R2 key and its content type |
| `common_gain_db`, `ceiling_dbfs`, `limit_over_ceiling_db`, `measurements` | how the MP3s were made |
| `uploaded` | false until the upload has run |

## Deliver

1. **Always:** send the MP3s to Anthony (SendUserFile), with one line each on what to listen for. Include
   any doubtful hits the practice flagged.
2. **Only when Anthony permits uploads** (the policy at the top). Until then, stop at "prepared, not
   uploaded" with the batch number reserved as above; the files stay ready. When uploads are permitted:
   1. `$S/run publish_prep.py upload W/practice/publish/entries.json` prints the R2 commands; run it again
      with `--yes` to upload. The bucket is lib/record's, through `npx wrangler`.
   2. `$S/run publish_prep.py apply W/practice/publish/entries.json --site ~/_agent_scratch/site` prepends
      the entries and adds the batch.
   3. In the site repo: branch, commit, push, PR, merge. Saving means merged.
   4. Check every audio URL returns 200 and the batch page plays.
   5. Send the phone notification through `lib/harness`'s `notify` (the topic stays in the Keychain).
   6. Record it with `$S/run runlog.py set ID published "uploaded: /skrng batch N"`.
