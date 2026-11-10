# HW002 against four references

Measured 1 October 2026 with `ears/mlab` (calibrated meters) on the Mac mini.
HW002 is the full render of `HW002_121`, all plugins loaded, unmastered.
The audio stays private. Only the numbers live here.

## The references

Anthony bought these four on Bandcamp as WAV files.
They replace SNTS *Lethal Storm*, which he dropped as a reference.

| Track | Length | Tempo | Integrated | True peak | PLR | LRA |
|---|---|---|---|---|---|---|
| BSLS — I Peed On You But You Were Never Mine | 5:21 | 160 | −4.3 LUFS | −0.0 dBTP | 4.3 | 6.1 |
| DJ JS x RedLotus — Hedon | 6:33 | 158 | −5.2 | −1.0 | 4.3 | 16.4 |
| KSMS — Roses Of Flesh And Blood | 6:17 | 155 | −7.2 | −0.4 | 6.9 | 8.2 |
| Remon Verhoeve — Patriotic | 5:49 | 155 | −6.8 | −0.2 | 6.6 | 5.6 |
| **HW002 (unmastered)** | 4:30 | 160 | −14.1 | +0.1 | 14.1 | 1.2 |

Tempo comes from onset autocorrelation. It reads HW002 as 159.94 BPM against a true 160.
Key detection gave margins too small to trust, so keys are left out.

## How the comparison was made

Whole tracks mix intros, breaks and outros, so they compare badly.
Each track was reduced to its peak: the 30 s window with the most high-frequency energy while the kick plays.
On HW002 this finds bars 125–144, the known absolute peak.
Tonal numbers are relative to each window's own total energy, so loudness cancels out.

The references are mastered loud and HW002 is not.
To test whether that explains the tonal gaps, HW002's peak was driven through the mlab limiter as hard as it goes.
It reached −6.7 LUFS, and no tonal band moved more than 0.8 dB.
So the gaps below are in the mix, not the master.

## Findings

### 1. Mids are scooped

From 1 kHz to 3.2 kHz, HW002 sits 6–8 dB below the reference mean.
It is below **all four** references in every band of that range.
This is where kick knock, percussion bite and distortion body live.

### 2. The deepest sub is missing

At 25–40 Hz, HW002 sits 7–9 dB below the reference mean, again below all four.
From 63 Hz to 200 Hz, HW002 sits 0–3 dB above the reference mean.
The kick's low cut is the likely cause; the old HW002 notes already list "remove aggressive kick low-cut".

### 3. Air is high

Around 10 kHz, HW002 sits about 5 dB above the mean, above all four.
Hedon is unusually dark, so the gap to the other three is smaller, about 3–4 dB.

### 4. The low end is not mono

Below 120 Hz the references have correlation 0.99–1.00, and side energy 22–45 dB under mid.
HW002 has correlation 0.88, and side energy only 12 dB under mid.
Every reference keeps its low end mono; HW002 does not.

### 5. The peak is less dense

In the peak window the references have a median block crest of 4.4–6.6 dB.
HW002 has 8.7 dB, and even maximum limiting only brings it to 7.5 dB.
The references get their density before the limiter: clipping, saturation and a fuller drum bus.

### 6. Loudness is a decision, not a gap

The references are mastered at −4 to −7 LUFS.
YouTube plays everything at about −14 LUFS, so it turns them down 7–10 dB.
On a Short, a louder master does not play louder; density and tone carry the impact.
The target is open question 11 in the interview, and stays Anthony's call.

### 7. The arrangement already follows the references

| | Main break (longest without kick) | Break near bar 80 | Peak after main break | Drop vs peak, highs |
|---|---|---|---|---|
| BSLS | bars 117–128 (12) | no (first at 98) | no (peak 76–95) | −2.8 dB |
| Hedon | 159–175 (17) | yes, 80–87 | yes (212–231) | −1.1 dB |
| KSMS | 98–124 (27) | yes, 82–96 | yes (129–147) | −2.9 dB |
| Patriotic | 133–152 (20) | yes, 80–96 | yes (172–190) | −1.4 dB |
| **HW002** | 82–96 (15) | yes, 82–96 | yes (125–144) | −3.4 dB |

Three of four break near bar 80, as HW002 does.
Three of four put the absolute peak after the main break, as HW002 does.
All four restart sparser than the peak; HW002 restarts sparsest.
HW002 has one break; every reference has two of 8 bars or more.
HW002 opens about 11 dB below its peak in the highs; the references open 1–5 dB below theirs.
That matters for the full track, not for the Short, which starts at a peak.

## Rubric seed

Each item has a measure and the reference range it must land in.
"Listen" items have no meter; Anthony judges them against the references.
Items 1–6 come from the old HW002 vs *Lethal Storm* notes.

| # | Criterion | How it is checked | Reference range | HW002 now |
|---|---|---|---|---|
| 1 | Main SFX withheld early, then builds | listen | — | open |
| 2 | Hat layers enter one at a time | listen; density steps per phrase | — | open |
| 3 | Kick scoops mark structure (bars ~37, ~121) | low-end dips per bar | — | present at bars 43–45 and 121–123 |
| 4 | A second percussion character from about bar 65 | listen | — | open |
| 5 | Drop restarts sparser than the peak | highs, first 8 bars after break vs peak | −1 to −3 dB | −3.4 dB, edge |
| 6 | Level and band A/B against references, with a spectrum analyzer | level-matched A/B | all at −14 LUFS | ready, see below |
| 7 | Low end mono below 120 Hz | correlation, side − mid | ≥ 0.99, ≤ −22 dB | 0.88, −12 dB: **fail** |
| 8 | Deep sub 25–40 Hz present | 1/3-octave vs reference mean | within ±3 dB | −7 to −9 dB: **fail** |
| 9 | Mids 1–3.2 kHz present | 1/3-octave vs reference mean | within ±3 dB | −6 to −8 dB: **fail** |
| 10 | Air near 10 kHz not excessive | 1/3-octave vs reference mean | within ±3 dB | +5 dB: **fail** |
| 11 | Peak density | median block crest, peak window | 4.4–6.6 dB | 8.7 dB: **fail** |
| 12 | Main break near bar 80; peak after it | kickless runs, peak window | 3 of 4 references | **pass** |
| 13 | Master true peak | after mastering | ≤ −1.0 dBTP | +0.1 dBTP (bar 81 hit) |
| 14 | Master loudness | integrated | Anthony decides | −14.1 LUFS |

## Listening setup

- `~/_agent_scratch/HW002/HW002_121_refs.als` is a copy of HW002 with four muted tracks, `REF BSLS` to `REF Patriotic`.
  The references are unwarped and level-matched to HW002 at −14 LUFS. Solo one to hear it, unsolo to return.
- `~/_agent_scratch/refs/HW002/matched/` holds 30 s peak excerpts of all five tracks at −14 LUFS, as WAV and MP3.

## Reproduce

```
uv run python -m mlab refs HW002.wav REFS_DIR --peaks --excerpts OUT_DIR
```

Run it inside `ears/mlab`. Known-answer checks for tempo, breaks and peak windows are in `calibration/checks.py` (`check_sections`).
