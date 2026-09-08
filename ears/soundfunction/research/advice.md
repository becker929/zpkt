# Production-literature sweep: signal chains and hypotheses for hard techno

*Scope: published advice specific to 2018+ industrial/hard techno (140–160 BPM, kick-and-rumble
driven), mapped onto this project's measures. Compiled 2026-09-07. Every source below was opened
(WebFetch, or the Cableguys manual PDF via Read) and is quoted or closely paraphrased from that
page; three pages that returned HTTP 403 (two Gearspace threads, one ModWiggler thread) were
found in search but are not cited, per instructions. Tiers follow `research/literature.md`:
1 reproduced science, 2 peer-reviewed, 3 reference work, 4 named expert practitioner, 5
industry/manufacturer, 6 community/other. A named practitioner's claim is tier 4 regardless of
the tier the hosting venue would otherwise get (so a Perc quote in MusicRadar is tier 4, not the
tier 5 the venue gets for its own unsigned technique articles) — the same convention
`literature.md` already uses.*

## A. Signal chains

Each chain is an ordered stage list with the parameter ranges sources actually state, and after
each stage the measure(s) it should move and the predicted direction. These are priors for a
device map, not settled facts — several stages carry disagreeing numbers from different sources,
noted inline.

### (i) The rumble kick

1. **Source: a second kick (or the same kick re-triggered) into a sampler/synth with a
   lengthened attack**, eliminating the snappy transient of the original hit. *"longer attack in
   Simpler"* to remove the click — Attack Magazine, "Dark Techno Rumble" (Beat Dissected), 2019,
   tier 5, https://www.attackmagazine.com/technique/beat-dissected/dark-techno-rumble/.
   → **rise time** ↑ (slower attack by design); **crest factor** of this layer ↓ (transient
   removed before anything else happens to it).

2. **Long, fully wet reverb.** Values disagree by a factor of 2–5 across sources: *"3 to 5
   seconds, 100% wet"* — MusicRadar, "Create a rumbling techno kick in 10 easy steps," tier 5,
   https://www.musicradar.com/how-to/rumbling-techno-kick; *"over 3 seconds"* fully wet — Studio
   Brootle, "Making A Techno Rumble Kick In Ableton Live," tier 5,
   https://www.studiobrootle.com/making-a-techno-rumble-kick-in-ableton-live-step-by-step/;
   *"1–2 seconds decay, 100% wet"* — Tracksensei, "How to Make a Techno Kick," tier 5,
   https://tracksensei.com/blog/how-to-make-a-techno-kick.
   → **fall to 20/40 dB** ↑↑ (this is the stage that manufactures the long tail);
   **share of energy after 50 ms** ↑↑; **crest factor** ↓ further.

3. **Low-pass the reverb tail, then EQ the whole rumble bus down to a narrow low band.**
   MusicRadar's exact device value: Auto Filter *"with the Filter Frequency set at 96.6Hz"* on
   the dark-verb return, then a later EQ Eight pass to *"notch out some boxy frequencies at
   135Hz."* Tracksensei gives a wider window: high-pass *"30–50 Hz"*, low-pass *"100–200 Hz"* on
   the whole rumble send. Attack Magazine's original *kick* (not the rumble return) is high-passed
   *"until approximately 50Hz"* with *"an additional dip of 3dB around 500Hz."*
   → **sub share (20–60 Hz)** ↑, **low share (60–150 Hz)** ↑, **mid/high share** ↓,
   **brightness (centroid)** ↓ sharply.

4. **Sidechain the rumble bus to the dry kick.** Studio Brootle: a compressor *"sidechain to main
   kick with ratio up to 4"*, tuning attack/release for *"pumping."* MusicRadar routes a separate
   compressor per parallel reverb send, sidechained from the same kick, so the delay and dark-verb
   tails duck independently and asynchronously from each other.
   → **pump depth** (measured on this bus, or on the bass stem once summed) ↑ at the kick's rate;
   **true sidechain on kick onsets** = yes by construction, since the trigger is the actual kick
   hit, not a synced LFO.

5. **Mono and notch the group.** MusicRadar: *"sum frequencies below 120Hz in mono"* after the
   parallel blend, having already notched 135 Hz; Riemann/Meindl's mastering-stage version of the
   same rule specifically for vinyl (see chain vi).
   → **sub share** stabilised/protected from stereo cancellation on mono playback (not one of the
   listed measures directly, but changes how reliably sub share reads across mono-summing
   systems); **stem levels (bass vs drums)** — this is the stage that decides how much of the
   rumble's level survives into "bass."

6. **Limiter to close out the group.** MusicRadar's last stage; generic across sources.
   → **crest factor** ↓ slightly; sets a ceiling ahead of the master chain.

*Disagreement flagged:* reverb length (1–2 s vs 3–5 s) and the low-pass point (96.6 Hz vs
100–200 Hz vs "under 150 Hz" per Future Proof Music School, tier 5,
https://futureproofmusicschool.com/blog/making-hard-techno-a-path-to-unique-sound-design) vary
enough between sources that "the rumble's low-pass point" is not a settled parameter — treat it as
a distribution, not a constant, when building the device-map prior.

### (ii) The kick + sub layer

1. **Two or more kick layers chosen for different registers**, most often by isolating the
   original kick and triggering a separate, tuned sub element from it. Two documented routings:
   (a) *audio-trigger*: isolate the kick (EQ + gate), use it to key a **gate on a continuous sine
   oscillator** tuned to a fixed note (example given: *C1*) so the sub only sounds on kick hits —
   Sound On Sound, "Kick It Up," tier 5, https://www.soundonsound.com/techniques/kick-it; (b)
   *sample layering into three explicit bands* — a "High," "Mid," and "Low" kick, individually
   EQ'd — Toolroom Academy, "How To Make Techno: Perfecting Your Kick," tier 5,
   https://toolroomacademy.com/features/how-to-make-techno-perfecting-your-kick/.
   → **sub share** ↑ (new dedicated low content); **landing pitch at 100 ms** is now
   *directly set* by the sub layer's tuning rather than emerging from a single pitch envelope.

2. **Align transients and check phase/polarity between layers.** *"make sure you're happy with
   the way their transients line up… deciding whether the kicks work best with the polarity of
   one sample inverted is a simple case of trial and error"* — Attack Magazine, "Layering Kick
   Drum Samples," tier 5,
   https://www.attackmagazine.com/technique/tutorials/layering-kick-drum-samples/2/. Corroborated
   by a named practitioner: Surgeon describes feeding *"two copies of the same output… into the
   mixer and treated them very differently, EQ'ing one to be the bass"* rather than fighting phase
   with identical processing — Sound On Sound, "Generations Part 2: Surgeon," tier 4,
   https://www.soundonsound.com/people/generations-part2-surgeon.
   → **rise time** and **kick body fall** protected from partial cancellation (unchecked phase
   would soften both); this stage has no source that *measures* the gain, see §C.

3. **Per-layer EQ + mono the low layers.** Toolroom Academy's exact values: High kick — cut
   *100 Hz*, low-pass *10 kHz*, optional *5 kHz* boost "for crack"; Mid kick — cut *150–170 Hz*;
   Low kick — roll off *below 30 Hz*, notch *350–400 Hz*.
   → **band shares** are explicitly apportioned per layer by design: the high layer supplies
   mid/high share and **brightness**, the low layer supplies **sub share**; the 350–400 Hz notch
   on the low layer is there specifically to keep it from bleeding into **mid share**.

4. **Group bus: light glue compression → group EQ → saturation → parallel compression (50% wet)
   → limiter → EQ'd reverb send.** Toolroom Academy's stated order and values: group EQ notches
   *"around 140Hz"* and *"around 400Hz"*; parallel blend at *50%* wet/dry; *"saturation makes
   everything a little bit louder and fatter, and shaves off the transient."*
   → **crest factor** ↓ (glue + parallel compression, but only partially — the 50% dry blend is
   explicitly there to keep some of it); **fall to 20/40 dB** shortened by the group compressor's
   release; **brightness** ↑ modestly from the saturation stage.

5. **Pitch/amp envelope choice on the synthesised layer.** Tracksensei's exact ranges: pitch
   envelope drops *"24–48 semitones… landing in 20–60 ms,"* fundamental *"45–55 Hz,"* amp envelope
   *"200–400 ms (punchy)"* or *"400–600 ms (rolling)"* — stated as two discrete regimes, not a
   continuum.
   → **landing pitch at 100 ms**: since the pitch envelope resolves by 60 ms at the latest per
   this source, a kick built this way should read a *stable* pitch by 100 ms; **fall to 20/40 dB**
   clusters near either ~200–400 ms or ~400–600 ms rather than spreading evenly between them (see
   H40).

### (iii) The hard/industrial kick body — distortion staging

1. **Source: a 909-style or synthesised kick, often pitched down.** Attack Magazine's Berghain
   example: a *TR-909 pitched down 8 semitones* layered with two subbier kicks — Attack Magazine,
   "Processing Berghain Kicks With Multiband Distortion," tier 5,
   https://www.attackmagazine.com/technique/tutorials/processing-berghain-kicks-with-multiband-distortion/.
   → **landing pitch at 100 ms** lowered by construction.

2. **Distortion/overdrive stage 1, applied before any EQ.** Explicit chain-order rule: *"Chain
   order matters: synthesis first, distortion second, EQ third, compression last… distortion
   creates new resonances that didn't exist in the clean signal, so earlier cuts get rewritten"* —
   Tracksensei. Value given elsewhere: *"Decapitator… pushing it hard… mix to around 50% rather
   than 100% wet to retain some of the original punch"* — The Producer School, "How to Create
   Hard Techno," tier 5,
   https://theproducerschool.com/blogs/featured-blogs/how-to-create-hard-techno-a-step-by-step-guide.
   Corroborated at tier 6: *"a 909 overdriven into a Mackie mixer"* described as *"extremely
   common"* — KVR Audio forum, "Creating this Techno Kick," tier 6,
   https://www.kvraudio.com/forum/viewtopic.php?t=416670.
   → **brightness** ↑ (new harmonic content); specific claim: *"generates harmonics at 100, 150,
   and 200 Hz that survive on small speakers where the 50 Hz fundamental never arrives"* —
   Tracksensei, so expect a **mid/low-mid share** bump at those frequencies independent of the
   fundamental; **crest factor** ↓ (peaks rounded/clipped).

3. **EQ after distortion, to correct what the distortion just added.** Values disagree on where
   to cut: *"around 250–300Hz"* — Attack Magazine, "Industrial Techno" (Beat Dissected), tier 5,
   https://www.attackmagazine.com/technique/beat-dissected/industrial-techno/; *"130–250Hz and
   700–1000Hz"* cuts with a *"60–100Hz"* boost — Audiotent, "Anatomy of the Techno Kick," tier 5,
   https://www.audiotent.com/blogs/production-tips/anatomy-of-the-techno-kick; *"140Hz"* and
   *"400Hz"* notches at the group stage — Toolroom Academy.
   → **mid share** ↓ at the targeted notch; **low share** ↑ if a low-shelf boost is used; the
   *point* of this stage, per Tracksensei's rule, is that it must come after distortion or it
   misses the harmonics distortion just created — see H33 for whether this actually suppresses
   the low-mid band in real kicks.

4. **A second, harsher distortion/bitcrush stage for top-end grit**, often on a duplicate layer
   with a shortened tail. *"D16 Decimort bitcrusher adds noise in the high end… attack and crispy
   distortion"* — Attack Magazine, "Industrial Techno." Similarly, a second kick copy with *"a
   steep low-cut, distorting it heavily… and shortening its decay so it acts as a punchy transient
   element"* — The Producer School.
   → **air/high share** ↑; **brightness** ↑ further; **rise time** of the blended kick sharpened
   (this layer's own fall is short by design, so its transient dominates the front of the sum).

5. **Compression last.** Tracksensei's rule again; the KVR consensus explicitly warns against the
   opposite outcome — one 403'd Gearspace thread aside, a fetchable KVR mix-clinic thread found
   posters agreeing a real mix was *"over compressed… the kick has no room to breathe and only the
   high freq transients come through"* and that the *"kicks transient is to loud… needs more of
   the thump part"* — KVR Audio forum, "What's wrong with my mix (hard techno)," tier 6,
   https://www.kvraudio.com/forum/viewtopic.php?t=498288.
   → **crest factor** ↓ (final glue); **fall to 20/40 dB** controlled by release; **kick level at
   the next beat** set here relative to beat length.

### (iv) Hats and top percussion

1. **Sample choice / resampling for character.** Deliberately avoiding excess highs at the sample
   stage — *"samples were deliberately chosen"* to avoid excessive high frequencies — Attack
   Magazine, "Grinding Analogue Techno" (Beat Dissected), tier 5,
   https://www.attackmagazine.com/technique/beat-dissected/grinding-analogue-techno/. Alternative:
   resample through a 12-bit sampler for *"digital crunch"* — Attack Magazine, "Industrial
   Techno."
   → sets the baseline **brightness** and **high/air share** before any processing.

2. **High-pass to remove low-mid clutter.** Named-practitioner version: Perc reduces his kicks to
   *"one kick layer and then maybe a sharp transient like the very start of a closed 909 hi-hat on
   top of it,"* high-passed at a high frequency so it stays *"barely noticeable"* and doesn't
   interfere with the kick — MusicRadar, "Perc: 5 things I've learned about music production,"
   2021, tier 4, https://www.musicradar.com/news/perc-5-things-ive-learned-in-music-production.
   → **low/low-mid share** ↓ toward zero; **brightness** ↑.

3. **Multiband distortion + tube saturation.** Full chain given for "crispy techno hi-hats":
   Kombinat Dva (multiband distortion) → low-cut EQ → D16 Redoptor (tube distortion) → Cytomic
   The Glue compressor (*"fast attack and release,"* blended with dry signal) → Waves J37 tape →
   FabFilter Pro-Q2 (high-pass + a *"10k cut"*) → NI RC-48 reverb → LFO Tool volume shaper for a
   sidechain effect — Audiotent, "Crispy Techno Hi-Hats," tier 5,
   https://www.audiotent.com/blogs/production-tips/crispy-techno-hi-hats.
   → **brightness** ↑, **high/air share** ↑, **crest factor** ↓ (noise floor raised by
   distortion, then partially restored by the dry blend at the compressor stage).

4. **Sidechain/duck the hat bus to the kick.** *"sidechain applied to rumble and hats so every
   layer ducks on the kick"* — Attack Magazine, "Dark Techno Rumble." Corroborated by the same
   LFO Tool volume-shaper stage in the Crispy Hats chain above.
   → **true sidechain on kick onsets** = yes on the hat/percussion bus, not only the bass stem;
   **pump depth** measurable on the high band (see H42).

5. **Texture-match distortion across all percussion**, not just hats. *"Distort and bit-crush
   percussion to match the kick's texture"* — Seedj, "Hard Techno Production Guide," tier 5,
   https://www.seedj.com/learn/hard-techno-production-guide. Attack Magazine's "Thumping Techno"
   gives concrete per-element treatments: snare *pitched down "nearly one octave,"* *"24dB/octave
   low-pass filter with mild resonance"*; tuned percussion through *heavy overdrive → 24dB/octave
   high-pass* — tier 5, https://www.attackmagazine.com/technique/beat-dissected/thumping-techno/.
   → **band shares** across the percussion group become more uniform/matched to the kick's own
   spectral signature than a "clean" drum-machine approach would produce.

### (v) The sidechain/ducking network

1. **Trigger source: route the kick's actual audio into the sidechain input ("Audio Trigger"),
   not a synced LFO.** *"Use the Audio triggering option when you want the ducking to precisely
   track the rhythm of the kick drum in your track — such as when the kick pattern is irregular…
   or features variations (fills, kick-free breaks, etc.)"* — Cableguys, *Nicky Romero Kickstart 2
   Manual* v2.0.9, p.9, tier 5 (manufacturer manual),
   https://downloads.cableguys.com/Nicky-Romero-Kickstart-2-Manual.pdf. The manual states Audio
   mode runs at *"10ms latency… and 16ms when [Anti-Click Smoothing is] on"*; Sync mode (a
   tempo-locked LFO, not a true sidechain) is *"completely latency-free"* but assumes a regular
   grid.
   → this stage **is** the "true sidechain on kick onsets" measure: only Audio-trigger routing
   produces ducking that actually tracks real onsets through kick-free bars and fills; a Sync-mode
   LFO would keep pumping through a bar with no kick (see H37).

2. **Split the duck by frequency band; low-band-only ("invisible") ducking is an explicit,
   named feature.** *"Using Kickstart 2's band split feature, you can duck only the low
   frequencies in a signal, leaving everything above a user-specified cutoff point unaffected…
   adjust the slider till the kick punches through clearly and the pumping effect seems to
   'disappear'"* — same manual, p.10, cutoff range *20 Hz–5.12 kHz*. The manufacturer explicitly
   distinguishes this "invisible" mode from audible pumping: *"Ducking can be done 'invisibly',
   applied only to the low frequencies… Or it can be made audible, to give a special groove or
   'pump' to the sound"* (p.3). Same distinction independently from a mixing tutorial using a
   different plugin: FabFilter Pro-MB in multiband mode lets *"the low frequencies duck out of the
   way, leaving our mids and highs intact"* — Boombox.io, "4 Tips for Mixing Low End," tier 5,
   https://boombox.io/blog/fabfilter-pro-mb-sidechain-compression-tutorial/, giving concrete
   values: *fast attack, ratio increased "all the way up," 20 ms lookahead, roughly −18 dB
   range*.
   → **pump depth** should differ *by band*: deeper in sub/low where the split routes the duck,
   shallower or absent in mid/high (see H34); this is a genuinely two-valued design choice
   (audible vs invisible), not a single settled target.

3. **Attack: fast, near-instant.** *"between 1 and 10 ms"* is the generic figure — Gearnews,
   "Sidechain Compression in Techno: 5 Effective Methods," tier 5,
   https://www.gearnews.com/sidechain-compression-in-techno-workshop/. The Boombox/FabFilter
   tutorial's multiband version pushes attack to effectively instant with a 20 ms lookahead
   instead.
   → **rise time** of the ducked element is not the limiting factor here — the duck engages
   essentially at the kick's true onset; **pump return time** is governed by release, next.

4. **Release: tempo-linked, but the actual hard-techno sources describe it as a curve *shape* and
   *note-value length*, not the "release ≈ 60000/BPM" formula that generic sidechain blogs give.**
   Gearnews states the formula explicitly (*"release (ms) ≈ 60,000 ÷ BPM"*, giving ~468 ms at 128
   BPM, with *"practical values between 200-350 ms"*) and a generic range of *"between 30 and 300
   ms."* The Kickstart manual instead offers curve **Length** quantised to *1/8, 1/4, 1/2, 1/1*
   note values (p.8) and two purpose-built **sub-bass curves (9–10)** with *"slower fade-ups for
   smoother ducking of low frequencies and greater kick drum impact"* (p.7) — a shape claim, not a
   millisecond number.
   → **pump return time** should correlate with beat length (as already found for H14, r = +0.25);
   the disagreement between "compute release from BPM" and "pick a note-value curve shape" is
   flagged in §C as a possible reason that correlation isn't tighter.

5. **Extend the same duck to the rumble bus and the hi-hat bus, not just the bassline.**
   *"sidechain applied to rumble and hats so every layer ducks on the kick"* — Attack Magazine,
   "Dark Techno Rumble."
   → **pump depth** and **true sidechain on kick onsets** apply on the high band too, not only the
   bass stem (H42).

6. **Automate the ratio down toward 1:1 approaching a breakdown, as an alternative to a riser.**
   *"gradually increase volume and reduce the sidechain effect and separation of the tracks…
   gradually more chaotic and messy as you get to a break"* — Perc, MusicRadar, tier 4.
   → **pump depth** should decline gradually (not jump) over several bars immediately before a
   breakdown in tracks using this technique (H47).

### (vi) The master chain for techno

1. **Leave headroom into the chain**, e.g. peak around **−6 dB** before mastering processing —
   Riemann Kollektion, "Riemann Techno Mastering Chain" product page, tier 5,
   https://riemannkollektion.com/products/free-download-riemann-techno-mastering-chain-2026-for-ableton-live
   (found via search, description text only — not independently re-verified beyond the search
   snippet, so treated as a weak citation; the same author's blog post below is the primary
   source for this chain's philosophy).

2. **Frequency-dependent compression: higher ratio and more gain reduction in the bass, lower
   ratio as frequency rises.** *"Use a high compression ratio in the bass area but reduce it in
   volume a bit. The higher you go with the frequencies the lower the ratio should be to keep the
   dynamics"* — Florian Meindl (founder, Riemann Mastering; mastering credits include Richie
   Hawtin, Radio Slave, Stephan Bodzin per the label's own bio), "After the Loudness War: Techno
   Mastering in 2021," Riemann Kollektion blog, tier 4,
   https://riemannkollektion.com/blogs/techno-producer-knowledge-hub/after-the-loudness-war-techno-mastering-2020.
   Meindl also states the reasoning to work *"without a limiter first so you can hear exactly what
   the compressors do"* and *"if an important element of the track needs that punchy dynamics then
   so be it – don't destroy it with a limiter."*
   → reshapes dynamics **by band** rather than with one broadband number; **kick body**
   sub/mid balance is decided before the brightness/limiting stages, not after.

3. **Gentle saturation / soft clipping before the limiter.** *"a chain of gentle saturation, a
   clipper and a limiter"* with the explicit framing that the limiter is *not* the primary loudness
   engine — Seedj, "Hard Techno Production Guide," tier 5. Same idea corroborated at tier 6: a
   Gearspace-style master bus described elsewhere in this sweep used *"a tape emulator at 30ips"*
   as a late gentle-saturation stage (this specific quote is from search-summary only and is not
   independently re-cited as a numbered claim below because the source page 403'd on fetch — flag
   only, do not treat as confirmed).
   → **brightness** ↑ slightly (harmonic lift); **crest factor** ↓ modestly; **integrated
   loudness** ↑ without relying solely on limiter gain reduction.

4. **Limiter as a safety net, not the main loudness tool.** Same Meindl source; also stated
   independently as *"staged soft clipping with limiter as safety, not primary loudness engine"* —
   The Producer School, "How to Create Hard Techno."
   → sets the final **crest factor** floor and **integrated loudness** ceiling.

5. **Automate a deliberate level gap between sections rather than mastering to one flat
   loudness.** *"automate a dB of difference between sections to keep drops physical"* — Seedj.
   → predicts **integrated loudness** measured per-section (not just per-track) should show
   intentional variance between drop and breakdown — one reason a single track-level LUFS number
   (as in H30) may undersell how loud the *drop itself* actually is.

6. **Avoid deep dynamic range specifically in the sub band, because club playback compresses it
   anyway.** *"Avoid very dynamic sub-bass in Techno because in a club the subwoofers will most
   likely run on maximum all the time anyway"* — Meindl.
   → predicts a *ceiling* on how much **pump depth** should survive into a finished master's low
   end even when the arrangement stage explicitly wants deep, audible pumping (chain v, stage 6) —
   a direct tension between two stages of the pipeline (H38).

7. **Mono below ~120–135 Hz — but the sources' stated reason for this is vinyl-cutting physics,
   not clubs in general.** *"mainly a 100% mono mix below 120hz so that the needle doesn't jump
   out of the groove"* — Meindl, explicitly about vinyl. MusicRadar's "10 easy steps" tutorial
   applies the same idea inside the kick's own bus (*"sum frequencies below 120Hz in mono"*) for a
   different, general-clarity reason.
   → affects how reliably **stem levels (bass vs drums)** and **sub share** read on a mono sum,
   but the *justification* differs by source — see §C.

8. **LUFS targets stated by sources disagree by roughly 2–3 LU**, all higher (louder) than this
   project's own corpus measurement:
   - *"up to −7 LUFS for Techno music"* (vs *"−12 LUFS"* for house) — Meindl, tier 4.
   - *"around −8 to −6 LUFS is typical for techno"* — Samplesound, "Mastering Techno: Loudness,
     Dynamics, and Club Readiness," tier 5,
     https://www.samplesoundmusic.com/blogs/news/mastering-techno-loudness-dynamics-and-club-readiness.
   - *"−6 to −5 LUFS integrated using staged soft clipping plus limiter"* — Future Proof Music
     School, tier 5.
   - This project's own H30 result: median **−10.0 LUFS**, quartiles −12.4/−8.3, n = 218 —
     `research/hypotheses.md`. See §C for the size of this gap.

## B. Hypotheses (H33–H47)

Register format matches `hypotheses.md`: claim, measure, a numeric prediction stated before any
test, the test, motivating source(s), and whether current data can test it now.

**H33. Distortion regenerates the low-mid band faster than the standard post-distortion EQ cut
removes it, so kicks keep audible low-mid energy despite near-universal advice to cut it there.**
Measure: kick body low-mid band share (roughly 150–400 Hz, the region the sources below target).
Prediction: median low-mid share across corpus kick bodies is at least 0.15 — i.e., not
suppressed to near-zero — despite three independent sources instructing a cut in exactly this
region. Test: compute the corpus median of kick-body low-mid share; compare against the near-zero
null a "successfully cut" kick would show. Sources: Attack Magazine, "Industrial Techno" (cut
"around 250–300Hz"); Audiotent, "Anatomy of the Techno Kick" (cuts "130–250Hz and 700–1000Hz");
Tracksensei (distortion "generates harmonics at 100, 150, and 200 Hz"). Testable now: corpus.

**H34. Band-split ("invisible") sidechain ducking produces a measurably deeper duck in the sub
band than in the low band on the bass stem, because the manufacturer feature specifically routes
the duck below a cutoff and leaves everything above it untouched.** Measure: pump depth computed
separately in sub (20–60 Hz) and low (60–150 Hz) bands on the bass stem at kick onsets. Prediction:
median sub-band pump depth exceeds low-band pump depth by at least 3 dB. Test: rerun the existing
bass-stem pump-depth method per band, compare medians (paired, Wilcoxon). Sources: Cableguys,
*Kickstart 2 Manual* p.10 ("duck only the low frequencies… leaving everything above… unaffected");
Boombox.io/FabFilter Pro-MB tutorial ("the low frequencies duck out of the way, leaving mids and
highs intact"). Testable now: excerpts (bass stems already separated for H13/H14).

**H35. Kicks with a strong post-distortion mid-band presence show a falling brightness slope
over their first 250 ms, because the corrective EQ stage that follows distortion (per the stated
chain-order rule) trims the top while the body's fundamental settles.** Measure: kick body mid
share (400 Hz–2 kHz) vs. kick body brightness slope. Prediction: negative rank correlation,
r ≤ −0.2. Test: Spearman correlation across corpus kick bodies. Sources: Tracksensei ("EQ
third… to keep the low end controlled"); Toolroom Academy (post-distortion notches at 140 Hz and
400 Hz). Testable now: corpus.

**H36. Real corpus kicks skew toward transient-forward and away from the "thump" that mixing
consensus says is missing — i.e., published complaint and published technique disagree about what
real kicks contain.** Measure: kick body sub share (20–60 Hz) in the first 250 ms. Prediction:
median corpus kick-body sub share is below 0.20. Test: compute the corpus median and compare to
0.20. Sources: Sound On Sound, "Q. How can I rescue my kick drum sound?" (transient-designer,
attack-forward remedy), tier 5, https://www.soundonsound.com/sound-advice/q-how-can-rescue-my-kick-drum-sound;
KVR Audio mix-clinic thread, "What's wrong with my mix (hard techno)" (posters diagnosing a real
mix as having a kick whose "transient is to loud… needs more of the thump part"), tier 6. Testable
now: corpus.

**H37. Because published sidechain guidance recommends tracking the kick's actual audio (a "true"
sidechain) specifically so ducking does not continue through kick-free bars, real bass stems show
little or no residual periodic ducking during bars with no kick.** Measure: bass-stem envelope
periodicity at the beat rate, restricted to bars flagged kick-free. Prediction: fewer than 10% of
kick-free bars show a detectable periodic amplitude dip at the beat rate on the bass stem. Test:
autocorrelation/periodicity check on the bass-stem envelope within kick-free-bar windows. Sources:
Cableguys, *Kickstart 2 Manual* p.9 (Audio trigger mode exists "when the kick pattern is
irregular… or features variations (fills, kick-free breaks, etc.)"). Testable now: excerpts
(needs kick-free-bar flags joined to bass-stem envelope, both of which exist separately in the
pipeline per H10/H11 and H13).

**H38. Mastering-stage advice to keep the sub band un-dynamic (because club subs run near maximum
regardless) sits in tension with arrangement-stage advice to make the pump deep and audible —
predicting that louder, more "club-ready" masters show shallower pump, not deeper.** Measure:
integrated loudness (LUFS) vs. pump depth on the bass stem. Prediction: negative Spearman
correlation, r ≤ −0.2. Test: Spearman correlation across the 218-track corpus (loudness and pump
depth are both already computed per H30/H13). Sources: Florian Meindl, "After the Loudness War"
("avoid very dynamic sub-bass in Techno because… the subwoofers will most likely run on maximum
all the time anyway"), tier 4; Gearnews sidechain workshop (the "classic" 6–12 dB audible-pump
target), tier 5. Testable now: corpus.

**H39. "Musical" sidechain curves (as opposed to a hard gate) leave a slow, audible fade-back-up
on the bass stem after each kick, because manufacturer sub-bass curves are explicitly built with
"slower fade-ups."** Measure: rise time (10–90%) of the bass-stem envelope's recovery after each
kick-triggered dip. Prediction: median recovery rise time exceeds 30 ms. Test: measure the
recovery slope of the bass-stem envelope following each detected duck, take the corpus/excerpt
median. Sources: Cableguys, *Kickstart 2 Manual* p.7 ("Sub bass sidechaining (9–10): … slower
fade-ups for smoother ducking of low frequencies and greater kick drum impact"). Testable now:
excerpts.

**H40. Because sources describe the industrial kick as two glued regimes — a 5–15 ms "click"
layer and an independently-chosen 200–400 ms or 400–600 ms "body" envelope, given as discrete
alternatives rather than a continuum — real kick-body fall times should be more spread out
(bimodal-leaning) than a single-decay-shape kick would produce.** Measure: kick body fall-to-20 dB
time, corpus-wide distribution. Prediction: interquartile range of kick-body fall time is at least
150 ms. Test: compute IQR across the corpus; inspect for bimodality (e.g., dip test or two-cluster
GMM fit) as a secondary check. Sources: Tracksensei ("click layer": 2–5 kHz, 5–15 ms duration;
amp envelope "200–400 ms (punchy) or 400–600 ms (rolling)" as two named alternatives). Testable
now: corpus.

**H41. Kick bodies got more frequency-segregated (fewer simultaneous "layers" doing several jobs
at once) over 2018–2026, following the trend a named practitioner reports in his own layer count.**
Measure: Shannon entropy of the kick-body band-share vector (sub/low/low-mid/mid/high/air) per
track, by year. Prediction: negative Spearman correlation between release year and band-share
entropy, r ≤ −0.15 (later kicks concentrate energy in fewer bands rather than spreading across
all of them). Test: Spearman correlation, entropy vs. year, across the corpus (band shares by
year already exist per H20). Sources: Perc, MusicRadar, "5 things I've learned" (kicks built from
"six or eight layers" in the past, now "most of my tracks now just have one kick layer"), tier 4.
Testable now: corpus.

**H42. The sidechain network extends past the bassline to the hi-hat/percussion bus, so a true,
kick-locked duck should be detectable on the high band of the drum stem, not only on the bass
stem.** Measure: pump depth computed on the air/high band (6 kHz+) envelope of the drum stem at
kick onsets. Prediction: median high-band pump depth is at least 1 dB (i.e., nonzero and
detectable, even though this band carries none of the kick's own energy). Test: apply the
existing pump-depth method to the drum stem's high band instead of the bass stem. Sources: Attack
Magazine, "Dark Techno Rumble" ("sidechain applied to rumble and hats so every layer ducks on the
kick"); Audiotent, "Crispy Techno Hi-Hats" (LFO Tool volume-shaper stage on the hat bus). Testable
now: excerpts (requires rerunning the pump-depth method on a new band/stem pairing, not yet done).

**H43. Modern hard-techno claps/snares are placed rhythmically more like a hi-hat (off-sixteenth,
avoiding beats 2 and 4) than like a classic backbeat instrument, extending H7's finding that a
clear backbeat is already a minority pattern.** Measure: share of clap/snare attacks landing on
off-eighth (or off-sixteenth) grid positions, computed the same way as H22's hi-hat measure.
Prediction: median share ≥ 0.4 — well above the 0.25 chance level for four slots, and closer to
H22's hi-hat result (0.50) than to a backbeat-concentrated pattern. Test: same attack-position
methodology as H6/H22/H7, applied to the clap/snare class. Sources: Attack Magazine, "Thumping
Techno" (snare "off-beat and 16th-note hits… unconventional placement"). Testable now: excerpts
(needs per-instrument-class attack positions from separated stems, not just the aggregate
"air"/"sub" attack classes already used for H6/H22).

**H44. Tracks with a strong, clean dedicated sub layer show tighter (less variable) landing pitch
than tracks relying on a single kick's pitch envelope, because a dedicated sub layer is tuned to
one fixed note rather than emerging from a decaying pitch sweep.** Measure: standard deviation of
landing pitch (Hz) across tracks, split by kick sub-share tertile. Prediction: the top tertile of
kick sub-share shows landing-pitch standard deviation at least 30% lower than the bottom tertile.
Test: compute landing-pitch SD within each sub-share tertile, compare. Sources: Sound On Sound,
"Kick It Up" (a fixed-note sub oscillator gated by the kick); Toolroom Academy ("Low Kick" as a
separately tuned, separately EQ'd layer). Testable now: corpus.

**H45. The 2–3 LU spread between published techno LUFS targets and this project's own measured
corpus median (−10.0 LUFS, quartiles −12.4/−8.3, vs. sources' −5 to −8 LUFS) is explained by
release format: vinyl-oriented releases in the corpus are mastered measurably quieter than
digital-only releases, consistent with the vinyl-specific caveats several sources attach to
low-end handling.** Measure: integrated loudness (LUFS), split by release-format metadata.
Prediction: median LUFS of vinyl-released corpus tracks is at least 2 LU quieter than digital-only
releases. Test: two-group comparison (Mann-Whitney) on integrated loudness by format, once format
metadata exists. Sources: Meindl's vinyl-specific mono/level caveats; the three disagreeing LUFS
targets in chain (vi), stage 8. Testable now: no — the corpus does not currently carry
per-track release-format (vinyl vs. digital) metadata.

**H46. In a blind listening test, listeners cannot reliably tell apart a low-band-only
("invisible") sidechain duck from a full-band duck at matched peak gain reduction, even though the
two are acoustically very different in band-resolved pump depth — because the manufacturer
feature is explicitly designed so "the pumping effect seems to disappear."** Measure: AB/X
discrimination accuracy between band-split and full-band ducking at matched dB. Prediction:
discrimination accuracy is at or below 60% correct (chance = 50%) when release ≤ 150 ms. Test:
AB/X listening test with matched-depth stimuli built from the excerpt corpus. Sources: Cableguys,
*Kickstart 2 Manual* p.3 ("Ducking can be done 'invisibly'… Or it can be made audible"), p.10;
Brøvig-Hanssen, Sandvik & Aareskjold-Drecker (2020), *Music Theory Online* 26(2), tier 2/3
(kick-triggered ducking delays the perceptual centre and is treated by producers as "a core
groove parameter" — motivating why the *audible* variant is prized even though the *inaudible*
variant is explicitly offered as an alternative). Testable now: listeners.

**H47. Anthony's own material, which H28 already shows keeps kick and rumble in a single mixed
layer (unlike the two-layer approach in his references), will show an abrupt rather than gradual
pump-depth decline before a breakdown, because Perc's "loosen the ratio gradually" technique
depends on having a separately addressable rumble/bass bus to loosen — something a one-layer
kick+rumble mix does not offer.** Measure: pump depth in the 16 bars preceding a labelled
breakdown, on the owner's tracks. Prediction: the drop in pump depth within the final 4 bars
before the breakdown accounts for at least 80% of the total pre-breakdown decline (i.e.,
concentrated/sudden, not spread across 8–16 bars). Test: bar-windowed pump-depth trend on the
owner's stems once available, compared against the gradual-decline pattern Perc describes. Sources:
Perc, MusicRadar, "5 things I've learned" (ratio-automation technique); `hypotheses.md` H28 (the
owner's one-layer finding). Testable now: owner_stems.

## C. Contradictions and folklore

- **Compression's place in the chain is not settled.** Tracksensei states a flat rule —
  *"synthesis first, distortion second, EQ third, compression last"* — but Toolroom Academy's own
  documented group chain puts a *glue compressor before* the saturation stage, then a *second*
  (parallel) compression stage *after* it: compression appears both before and after distortion in
  the one chain that gives concrete plugin order. No source reconciles this; both are presented as
  simply "the chain," not as competing options.

- **LUFS targets for "techno" disagree by roughly 2–3 LU among sources that all claim to state the
  genre norm** — Meindl's *"up to −7 LUFS"*, Samplesound's *"−8 to −6 LUFS,"* and Future Proof
  Music School's *"−6 to −5 LUFS"* — and this project's own corpus measurement (H30: median −10.0
  LUFS) sits quieter than every one of them. Either the fetched tutorials describe a louder,
  more commercial/streaming-oriented subset of "techno" than the corpus actually contains, or the
  corpus itself is not being mastered to the loudness these sources treat as standard; nothing in
  the sources distinguishes club-only from streaming-targeted masters, which is exactly the gap
  H45 tries to close.

- **Filter steepness: folklore says "just high-pass it"; the one place practitioners actually
  debated a number pushed back hard.** Several kick/rumble tutorials recommend high-passing low
  frequencies (Attack Magazine's kick at "approximately 50Hz," Tracksensei's rumble send at
  "30–50 Hz") without ever specifying a slope. The one fetched source where multiple named
  posters weighed in on an actual slope value flatly rejected a steep one: *"Your lowcut @ 30hz
  96dB/oct is WAY TOO STEEP,"* recommending *"18dB/oct usually"* instead, and tying the steep
  filter to audible phase problems — KVR Audio, "What's wrong with my mix (hard techno)," tier 6.
  No tutorial in this sweep gives a slope recommendation at all, so the "just high-pass it" advice
  is silent on exactly the parameter the one community discussion flagged as consequential.

- **Transient vs. thump is argued both ways, by different authorities, with no measurement on
  either side.** Perc's stated aesthetic is maximal restraint — kicks reduced to as few as one
  layer, transients kept "barely noticeable." The KVR mix-clinic thread diagnoses the *opposite*
  failure mode in a real mix — a kick that is *all* transient and no thump. Both are offered as
  correctives to a bad kick, which only makes sense if "how much transient vs. body" is a
  contested design axis rather than a settled rule; neither source offers a number (H36 tries to
  measure where the corpus actually sits).

- **The "release = 60000/BPM" sidechain formula is common in generic EDM-production writing but
  does not appear in any hard-techno-specific source in this sweep.** Gearnews states the formula
  outright. Every hard-techno-specific source found instead describes release as a *curve shape*
  or a *note-value length* (Cableguys' 1/8–1/1 Length control, the purpose-built "slower fade-up"
  sub-bass curves) rather than an arithmetic function of tempo. The formula may be a
  generic-EDM-blog convention that does not actually describe how hard-techno producers set this
  parameter — worth treating as folklore until tested (this is part of the motivation for the
  weak H14 correlation of r = +0.25 rather than something tighter).

- **Phase/polarity checking between layered kicks is universally recommended and never
  measured.** Attack Magazine, Toolroom Academy, and (independently) Surgeon's own description of
  differentiating duplicated layers by EQ rather than fighting phase all treat phase alignment as
  necessary groundwork — but not one source quantifies the before/after (in dB of low end, or in
  any of this project's measures). It is treated as self-evidently correct rather than
  demonstrated.

- **"Mono below 120 Hz" is stated for two different reasons that get blurred together.** Meindl's
  stated justification is specifically vinyl-cutting physics ("so the needle doesn't jump out of
  the groove"). MusicRadar's kick-bus version of the same numeric rule ("sum frequencies below
  120Hz in mono") is applied for general mix clarity, with no vinyl in the picture at all. Sources
  that repeat "mono your bass below ~120 Hz" as a blanket club/mastering rule are generalising a
  claim past the specific physical justification the mastering engineer actually gave for it.

## D. Sources

*Tier 4-or-better sources: 15 (of 33 total). Tier 4 requires a named practitioner regardless of
venue, per the convention already used in `literature.md`.*

**Tier 1/2 (reproduced science / peer-reviewed) — reused from `literature.md`, directly relevant
to the hypotheses above:**

1. Witek, M.A.G. et al. (2014), "Syncopation, Body-Movement and Pleasure in Groove Music," *PLoS
   ONE* 9(4):e94446. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3989225/
2. Brøvig-Hanssen, R., Sandvik, B.E., Aareskjold-Drecker, J.M. (2020), "Dynamic Range Processing
   and Its Influence on Perceived Timing in Electronic Dance Music," *Music Theory Online* 26(2).
   https://www.mtosmt.org/issues/mto.20.26.2/mto.20.26.2.brovighanssen.html
3. Ziemer, T. & Linke, S. (2024), "An Audio-Perspective on the Divergent Paths of Techno in
   Germany and the United States," *TISMIR* 9(1). https://transactions.ismir.net/articles/10.5334/tismir.324
4. Zehren, M., Alunno, M., Bientinesi, P. (2024), "Interpretability of Methods for Switch Point
   Detection in Electronic Dance Music," *Signals* 5(4). https://www.mdpi.com/2624-6120/5/4/36
5. Lakatos, S. (2000), "A common perceptual space for harmonic and percussive timbres,"
   *Perception & Psychophysics* 62(7). https://link.springer.com/article/10.3758/BF03212144
6. Repp, B.H. (2008), "A filled duration illusion in music." https://pmc.ncbi.nlm.nih.gov/articles/PMC2916667/
7. Peeters, G. et al. (2011), "The Timbre Toolbox," *JASA* 130(5).
   https://www.mcgill.ca/mpcl/files/mpcl/peeters_2011_jasa.pdf

**Tier 3 (reference work) — reused from `literature.md`:**

8. Zeiner-Henriksen, H.T. (2010), "Moved by the Groove," in Danielsen (ed.), *Musical Rhythm in
   the Age of Digital Reproduction*. https://www.researchgate.net/publication/291171696
9. Butler, M.J. (2006), *Unlocking the Groove*, Indiana University Press.
   https://archive.org/details/unlockinggroover00butl
10. Iler, D. (2011), "Formal Devices of Trance and House Music," MM thesis, UNT.
    https://digital.library.unt.edu/ark:/67531/metadc103332/

**Tier 4 (named practitioner) — newly opened this session:**

11. Perc (Ali Wells), "5 things I've learned about music production," MusicRadar, 2021.
    https://www.musicradar.com/news/perc-5-things-ive-learned-in-music-production
12. Perc (Ali Wells), "Perc: In The Studio," Attack Magazine.
    https://www.attackmagazine.com/features/interview/perc-in-the-studio/
13. Florian Meindl, "After the Loudness War: Techno Mastering in 2021," Riemann Kollektion blog.
    https://riemannkollektion.com/blogs/techno-producer-knowledge-hub/after-the-loudness-war-techno-mastering-2020
14. Surgeon, "Generations Part 2: Surgeon," Sound On Sound.
    https://www.soundonsound.com/people/generations-part2-surgeon
15. Klangkuenstler, interview, Decoded Magazine, 2017 (reused from `literature.md` — "punchy and
    dirty drums," thin single-quote source). https://www.decodedmagazine.com/klangkuenstler-interview-2017/

**Tier 5 (industry/manufacturer, unsigned technique articles):**

16. Attack Magazine, "Dark Techno Rumble" (Beat Dissected), 2019.
    https://www.attackmagazine.com/technique/beat-dissected/dark-techno-rumble/
17. Attack Magazine, "Processing Berghain Kicks With Multiband Distortion."
    https://www.attackmagazine.com/technique/tutorials/processing-berghain-kicks-with-multiband-distortion/
18. Attack Magazine, "Industrial Techno" (Beat Dissected).
    https://www.attackmagazine.com/technique/beat-dissected/industrial-techno/
19. Attack Magazine, "Grinding Analogue Techno" (Beat Dissected).
    https://www.attackmagazine.com/technique/beat-dissected/grinding-analogue-techno/
20. Attack Magazine, "Thumping Techno" (Beat Dissected).
    https://www.attackmagazine.com/technique/beat-dissected/thumping-techno/
21. Attack Magazine, "Layering Kick Drum Samples."
    https://www.attackmagazine.com/technique/tutorials/layering-kick-drum-samples/2/
22. MusicRadar, "Create a rumbling techno kick in 10 easy steps."
    https://www.musicradar.com/how-to/rumbling-techno-kick
23. Studio Brootle, "Making A Techno Rumble Kick In Ableton Live."
    https://www.studiobrootle.com/making-a-techno-rumble-kick-in-ableton-live-step-by-step/
24. Audiotent, "Crispy Techno Hi-Hats." https://www.audiotent.com/blogs/production-tips/crispy-techno-hi-hats
25. Audiotent, "Anatomy of the Techno Kick." https://www.audiotent.com/blogs/production-tips/anatomy-of-the-techno-kick
26. Sound On Sound, "Kick It Up." https://www.soundonsound.com/techniques/kick-it
27. Sound On Sound, "Q. How can I rescue my kick drum sound?"
    https://www.soundonsound.com/sound-advice/q-how-can-rescue-my-kick-drum-sound
28. Samplesound, "Mastering Techno: Loudness, Dynamics, and Club Readiness."
    https://www.samplesoundmusic.com/blogs/news/mastering-techno-loudness-dynamics-and-club-readiness
29. Gearnews, "Sidechain Compression in Techno: 5 Effective Methods for Punching Kicks."
    https://www.gearnews.com/sidechain-compression-in-techno-workshop/
30. Boombox.io, "4 Tips for Mixing Low End: FabFilter Pro MB & Sidechain Compression Tutorial."
    https://boombox.io/blog/fabfilter-pro-mb-sidechain-compression-tutorial/
31. Cableguys, *Nicky Romero Kickstart 2 Manual* v2.0.9 (manufacturer manual, read in full).
    https://downloads.cableguys.com/Nicky-Romero-Kickstart-2-Manual.pdf
32. Elektron, *Digitakt User Manual* (Overdrive parameter, p.44), via ManualsLib.
    https://www.manualslib.com/manual/2166470/Elektron-Digitakt.html
33. Ableton, "Sidechain Compression: Part 1 – Concepts and History" (definitions only; thin on
    techno-specific numbers). https://www.ableton.com/en/blog/sidechain-compression-part-1/
34. Tracksensei, "How to Make a Techno Kick: Sound Design From Scratch."
    https://tracksensei.com/blog/how-to-make-a-techno-kick
35. Toolroom Academy, "How To Make Techno: Perfecting Your Kick."
    https://toolroomacademy.com/features/how-to-make-techno-perfecting-your-kick/
36. Future Proof Music School, "How to Make Hard Techno: Kick Design, Rumble, and Club Mixing."
    https://futureproofmusicschool.com/blog/making-hard-techno-a-path-to-unique-sound-design
37. The Producer School, "How to Create Hard Techno: A Step-by-Step Guide."
    https://theproducerschool.com/blogs/featured-blogs/how-to-create-hard-techno-a-step-by-step-guide
38. Seedj, "Hard Techno Production Guide." https://www.seedj.com/learn/hard-techno-production-guide
39. FabFilter, Pro-MB Help, "External Sidechaining" (procedural only; no genre-specific numbers
    found). https://www.fabfilter.com/help/pro-mb/support/externalsidechaining

**Tier 6 (community/other):**

40. KVR Audio forum, "Creating this Techno Kick (Overdrive, distortion, fuzz, saturation)?"
    https://www.kvraudio.com/forum/viewtopic.php?t=416670
41. KVR Audio forum, "What's wrong with my mix (hard techno)."
    https://www.kvraudio.com/forum/viewtopic.php?t=498288

**Found but not cited (page would not open — excluded per instructions):** a Gearspace thread on
master-bus chains for "softer techno" (403), a Gearspace thread "Help making Techno kicks like
these" (403), a Gearspace Q&A with Ansome/Kieran Whitefield (403), and a ModWiggler thread on
techno rumble and sidechaining (403).
