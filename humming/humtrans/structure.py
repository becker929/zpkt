"""Tempo and key from a hummed take, against the label's own tempo and key.

    python3 -m humtrans.structure

HumTrans hummers sang along with the MIDI, so the label's tempo is the tempo
they hummed at. The label's key signature is checked against the label's own
notes first; only recordings where it fits are used as key truth.

Tempo, three estimators of the beat period:
  audio     librosa's tempogram peak on the recording (no notes needed)
  onsets    the same tempogram, built from the pYIN note starts only
  both      audio tempogram times the onset tempogram
Each is scored as right (within 4%), half, double, other; and its confidence
(how much the top peak beats the best non-multiple rival) is checked against
being right (AUROC).

Key, from duration-weighted pitch classes of the hummed notes (pYIN, tuning
removed): Krumhansl-Kessler and Temperley-Kostka-Payne profiles, 24 keys.
Scored as exact, relative major/minor, fifth away, other; confidence is the
correlation margin between the best and second-best key.
"""
import json
from collections import Counter, defaultdict

import numpy as np
import pretty_midi

from .common import CACHE, MIDI, OUT, WAV, load_notes, ref_notes, split
from .pitchbench import auroc

KK_MAJ = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
KK_MIN = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
TKP_MAJ = [0.748, 0.060, 0.488, 0.082, 0.670, 0.460, 0.096, 0.715, 0.104, 0.366, 0.057, 0.400]
TKP_MIN = [0.712, 0.084, 0.474, 0.618, 0.049, 0.460, 0.105, 0.747, 0.404, 0.067, 0.133, 0.330]


def key_scores(hist, maj, mnr):
    """Correlation with each of 24 keys: 0-11 major tonic, 12-23 minor tonic."""
    out = []
    for prof in (maj, mnr):
        for t in range(12):
            out.append(np.corrcoef(hist, np.roll(prof, t))[0, 1])
    return np.array(out)


def key_relation(est, true):
    """exact / relative / fifth / parallel / other, for keys numbered as pretty_midi does."""
    if est == true:
        return "exact"
    et, emin = est % 12, est >= 12
    tt, tmin = true % 12, true >= 12
    if emin != tmin and ((not tmin and et == (tt + 9) % 12) or (tmin and et == (tt + 3) % 12)):
        return "relative"
    if emin == tmin and (et - tt) % 12 in (5, 7):
        return "fifth"
    if emin != tmin and et == tt:
        return "parallel"
    return "other"


def tempo_curve(onset_env, sr, hop):
    import librosa
    tg = librosa.autocorrelate(onset_env - onset_env.mean())
    tg[0] = 0
    lags = np.arange(len(tg))
    bpm = 60 * sr / (hop * np.maximum(lags, 1))
    keep = (bpm >= 40) & (bpm <= 240)
    return bpm[keep], np.maximum(tg[keep], 0)


def pick(bpm, strength):
    """Top tempo, and its margin over the best rival that is not a 2x or 3x relative."""
    i = int(np.argmax(strength))
    top = bpm[i]
    ratio = bpm / top
    related = np.zeros(len(bpm), bool)
    for r in (0.5, 1 / 3, 2 / 3, 1, 1.5, 2, 3):
        related |= np.abs(ratio / r - 1) < 0.06
    rival = strength[~related].max() if (~related).any() else 0
    return float(top), float((strength[i] - rival) / (strength[i] + 1e-9))


def tempo_class(est, true):
    r = est / true
    for name, v in (("right", 1), ("half", 0.5), ("double", 2), ("third", 1 / 3), ("triple", 3),
                    ("two-thirds", 2 / 3), ("three-halves", 1.5)):
        if abs(r / v - 1) < 0.04:
            return name
    return "other"


def main():
    import librosa
    sr, hop = 22050, 512
    keys = split("TEST") + split("VALID")
    tempo = defaultdict(lambda: {"class": Counter(), "conf": [], "right": []})
    key_rows = []
    label_key_fit = []
    for k in keys:
        m = pretty_midi.PrettyMIDI(str(MIDI / f"{k}.mid"))
        true_bpm = float(m.get_tempo_changes()[1][0])
        y, _ = librosa.load(WAV / f"{k}.wav", sr=sr)
        env_audio = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
        iv, p, _ = load_notes(CACHE / "pyin" / f"{k}.json")
        env_on = np.zeros_like(env_audio)
        for s in iv[:, 0]:
            j = int(s * sr / hop)
            if j < len(env_on):
                env_on[j] += 1
        env_on = np.convolve(env_on, np.hanning(5), "same")
        curves = {"audio": tempo_curve(env_audio, sr, hop), "onsets": tempo_curve(env_on, sr, hop)}
        b, sa = curves["audio"]
        _, so = curves["onsets"]
        curves["both"] = (b, sa / (sa.max() + 1e-9) * so / (so.max() + 1e-9))
        for name, (bpm, st) in curves.items():
            est, conf = pick(bpm, st)
            c = tempo_class(est, true_bpm)
            tempo[name]["class"][c] += 1
            tempo[name]["conf"].append(conf)
            tempo[name]["right"].append(c == "right")

        # Key truth: the label's signature, kept only if the label's own notes agree with it.
        ks = m.key_signature_changes
        riv, rp = ref_notes(k)
        rhist = np.bincount(rp.astype(int) % 12, weights=riv[:, 1] - riv[:, 0], minlength=12)
        if not ks:
            continue
        true_key = ks[0].key_number
        label_est = int(np.argmax(key_scores(rhist, TKP_MAJ, TKP_MIN)))
        fits = key_relation(label_est, true_key) in ("exact", "relative")
        label_key_fit.append(fits)
        if not fits:
            continue
        # The hummed notes, in the label's octave frame: pitch classes do not
        # care about octave, only about tuning, which pYIN notes already remove.
        hist = np.bincount(p.astype(int) % 12, weights=iv[:, 1] - iv[:, 0], minlength=12)
        # Hummers were cued with the label's pitches, but the U/D suffix does not
        # move pitch class. Label key and hummed key should match.
        row = {"key": k, "true": true_key}
        for name, (maj, mnr) in (("kk", (KK_MAJ, KK_MIN)), ("tkp", (TKP_MAJ, TKP_MIN))):
            sc = key_scores(hist, maj, mnr)
            order = np.argsort(sc)[::-1]
            row[name] = key_relation(int(order[0]), true_key)
            row[name + "_margin"] = float(sc[order[0]] - sc[order[1]])
            row[name + "_label"] = key_relation(int(np.argmax(key_scores(rhist, maj, mnr))), true_key)
        key_rows.append(row)

    res = {"recordings": len(keys), "tempo": {}, "key": {}}
    for name, d in tempo.items():
        res["tempo"][name] = {"class": {c: round(v / len(keys), 4) for c, v in d["class"].most_common()},
                              "auroc_conf_vs_right": round(auroc(d["conf"], d["right"]), 3),
                              "right_when_conf_top_half": round(float(np.mean(np.array(d["right"])[np.array(d["conf"]) >= np.median(d["conf"])])), 4),
                              "right_when_conf_bottom_half": round(float(np.mean(np.array(d["right"])[np.array(d["conf"]) < np.median(d["conf"])])), 4)}
    res["key"]["label_signature_fits_label_notes"] = round(float(np.mean(label_key_fit)), 4)
    res["key"]["recordings_with_key_truth"] = len(key_rows)
    for name in ("kk", "tkp"):
        rel = Counter(r[name] for r in key_rows)
        res["key"][name] = {"hummed": {c: round(v / len(key_rows), 4) for c, v in rel.most_common()},
                            "from_label_notes": {c: round(v / len(key_rows), 4) for c, v in Counter(r[name + "_label"] for r in key_rows).most_common()},
                            "auroc_margin_vs_exact": round(auroc([r[name + "_margin"] for r in key_rows], [r[name] == "exact" for r in key_rows]), 3)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "structure.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
