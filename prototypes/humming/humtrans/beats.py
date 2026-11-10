"""Tempo and meter from a hummed take with Beat This! (Foscarin, Schlueter and Widmer, ISMIR 2024).

    python3 -m humtrans.beats [small0|final0]

Same truth and classes as structure.py: the label's tempo, and whether the
estimate is right, half, double or something else. Tempo is the median
inter-beat interval of the predicted beats. Meter is beats per bar from the
predicted downbeats (median count between them), against the label's time
signature numerator. Beat This! is trained on music mixes, never on solo
humming, so this measures how far a strong general tracker carries over.
"""
import json
import sys
from collections import Counter

import numpy as np
import pretty_midi

from .common import MIDI, OUT, WAV, split
from .structure import tempo_class


def main():
    from beat_this.inference import File2Beats
    ckpt = sys.argv[1] if len(sys.argv) > 1 else "small0"
    f2b = File2Beats(checkpoint_path=ckpt, device="cpu", dbn=False)
    keys = split("TEST") + split("VALID")
    tempo, meter = Counter(), Counter()
    for k in keys:
        m = pretty_midi.PrettyMIDI(str(MIDI / f"{k}.mid"))
        true_bpm = float(m.get_tempo_changes()[1][0])
        true_num = m.time_signature_changes[-1].numerator if m.time_signature_changes else 4
        beats, downs = f2b(str(WAV / f"{k}.wav"))
        if len(beats) < 3:
            tempo["no beats"] += 1
            continue
        tempo[tempo_class(60 / np.median(np.diff(beats)), true_bpm)] += 1
        if len(downs) >= 2:
            counts = [np.sum((beats >= a) & (beats < b)) for a, b in zip(downs[:-1], downs[1:])]
            est = int(np.median(counts))
            meter["right" if est == true_num else f"{est} for {true_num}"] += 1
        else:
            meter["no downbeats"] += 1
    res = {"checkpoint": ckpt, "recordings": len(keys),
           "tempo": {c: round(v / len(keys), 4) for c, v in tempo.most_common()},
           "beats_per_bar": {c: round(v / len(keys), 4) for c, v in meter.most_common(8)}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"beats_{ckpt}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
