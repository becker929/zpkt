"""Paths, split keys and note I/O shared by the HumTrans experiments."""
import json
from pathlib import Path

import numpy as np
import pretty_midi

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "datasets" / "humtrans"
WAV = DATA / "wav_data_sync_with_midi"
MIDI = DATA / "midi_data"
# Transcriptions are regenerable and large in count, so they sit beside the
# (uncommitted) dataset rather than in out/.
CACHE = REPO / "datasets" / "humtrans_out"
OUT = REPO / "out" / "humtrans"


def split(name):
    """Official split: 'TRAIN', 'VALID' or 'TEST'."""
    return json.loads((DATA / "train_valid_test_keys.json").read_text())[name]


def ref_notes(key):
    """Reference notes as (intervals [n,2] seconds, pitches [n] MIDI numbers)."""
    notes = pretty_midi.PrettyMIDI(str(MIDI / f"{key}.mid")).instruments[0].notes
    iv = np.array([[n.start, n.end] for n in notes]).reshape(-1, 2)
    return iv, np.array([n.pitch for n in notes], float)


def save_notes(path, iv, pitch, **extra):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"intervals": np.asarray(iv).tolist(),
                                "pitches": np.asarray(pitch).tolist(), **extra}))


def load_notes(path):
    d = json.loads(path.read_text())
    return np.array(d["intervals"], float).reshape(-1, 2), np.array(d["pitches"], float), d
