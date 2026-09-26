# Listening guide

Set your monitor volume once, at a comfortable level, and leave it. Numbers are in RESULTS.md.
Re-run everything with `python3 run_experiments.py` (it reshuffles the blind test).

1. **Loudness bias (Ch. 8, 10).** Play `01_blind_X` and `01_blind_Y`. Pick the one that sounds better. Then open the answer key. They are the same audio; one is 1 dB louder.
2. **LUFS vs peak (missing chapter).** Compare the two `02_master_*` files, then the two `02_*_after_normalization` files. The second pair is what a -14 LUFS streaming service plays. The crushed master is no longer louder, just flatter: its peaks sit about 4 dB lower.
3. **Inter-sample peaks.** Load `03_isp_sine.wav` in your DAW. A sample-peak meter reads -0.1 dBFS; the true signal peaks near +3 dBTP. The crushed master also clips after AAC encoding; the gentle master (-1 dBTP) does not.
4. **Dither (Ch. 4).** VOLUME LOW FIRST, these are boosted 60 dB. The truncated fade turns into gritty, pitched distortion as it dies. The dithered fade stays a clean tone under steady hiss.
5. **Attack/release (Ch. 10).** All five drum files are level-matched, so only the envelope changed. Slow attack lets the hit through before clamping, which is "punch." Slow release holds the gain down, flattening the groove.
