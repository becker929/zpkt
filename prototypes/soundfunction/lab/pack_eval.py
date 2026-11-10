#!/usr/bin/env python3
"""Use a sample pack's own folder names as labels: how well does the meter's model name them,
and what happens when the pack joins the training set?   python3 lab/pack_eval.py lab/drive/reports/pack-VEC.csv"""
import csv, json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import cross_val_predict, StratifiedKFold
ROOT = Path(__file__).resolve().parent.parent
MODEL = json.load(open(ROOT / "out" / "classifier_union3.json"))["model"]
FEATS = MODEL["features"]
# folder name -> job. Leaf names first (cymbal sub-folders differ), then the parent category.
LEAF = {"close hh": "hat", "open hh": "hat", "crash": "space", "reverse crash": "space", "ride": "hat", "reverb and fx kicks": None, "fx kicks": None, "gatefx": None}
JOB = {"bassdrums": "kick", "claps": "clap", "cymbals": "hat", "snares": "clap", "percussion": "hook", "offbeat bass": "hook", "303 acid": "hook", "long basses": "rumble", "synths": "hook", "special sounds": "space", "sounds": "space", "fx": "space"}

def job_of(folder):
    parts = [x.lower().replace("vec1 ", "").replace("vec2 ", "") for x in folder.split("/")]
    leaf = parts[-1]
    for k, v in LEAF.items():
        if leaf.endswith(k): return v          # None = a kick with effects on it, left out
    for part in reversed(parts):
        for k, v in JOB.items():
            if part == k or part.endswith(" " + k) or part.startswith(k): return v
    return None

rows = list(csv.DictReader(open(sys.argv[1])))
X, y, folders = [], [], []
for r in rows:
    j = job_of(r["folder"])
    if j is None or float(r["seconds"]) > 3.0: continue      # one-shots only, folders with a clear job
    X.append([float(r[f]) for f in FEATS]); y.append(j); folders.append(r["folder"].split("/")[-1])
X, y = np.array(X), np.array(y)
print(f"{len(y)} labelled one-shots from folders: " + ", ".join(f"{j} {int((y == j).sum())}" for j in sorted(set(y))))
# 1 the meter's current model on them
z = (X - np.array(MODEL["mean"])) / np.array(MODEL["scale"]); logits = np.array(MODEL["bias"]) + z @ np.array(MODEL["weights"]).T
pred = np.array(MODEL["classes"])[logits.argmax(1)]
acc = float((pred == y).mean()); rec = {j: round(float((pred[y == j] == j).mean()), 2) for j in sorted(set(y))}
print(f"meter model on the pack: {acc:.0%}  recall {rec}")
conf = {}
for j in sorted(set(y)):
    calls = pred[y == j]; conf[j] = {c: int((calls == c).sum()) for c in sorted(set(calls))}
print("what it calls each folder job:", json.dumps(conf))
# 2 the pack on its own, cross-validated, same seven measures
cv = StratifiedKFold(5, shuffle=True, random_state=0)
p2 = cross_val_predict(make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)), X, y, cv=cv)
print(f"pack-only model, 5-fold: {float((p2 == y).mean()):.0%}  recall { {j: round(float((p2[y == j] == j).mean()), 2) for j in sorted(set(y))} }")
# 3 transfer: pack model -> the 318 real pack hits from part two, and -> corpus hits
def load(path):
    rs = list(csv.DictReader(open(path))); m = {"hat_closed": "hat", "hat_open": "hat", "perc": "hook", "stab": "hook", "pad": "space", "riser": "space", "impact": "space"}
    return np.array([[float(r[f]) for f in FEATS] for r in rs]), np.array([m.get(r["sound"], r["sound"]) for r in rs])
model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)).fit(X, y)
for name, path in [("part-two real packs", ROOT / "out" / "library_real.csv"), ("corpus hits", ROOT / "out" / "library_corpus.csv")]:
    Xt, yt = load(path); keep = np.isin(yt, list(set(y))); pt = model.predict(Xt[keep])
    print(f"pack model -> {name}: {float((pt == yt[keep]).mean()):.0%} on {int(keep.sum())} hits")
# 4 all four domains together, cross-validated, accuracy per domain
Xs, ys = load(ROOT / "out" / "library_synth2.csv"); Xp, yp = load(ROOT / "out" / "library_real.csv"); Xc, yc = load(ROOT / "out" / "library_corpus.csv")
Xa = np.vstack([Xs, Xp, Xc, X]); ya = np.concatenate([ys, yp, yc, y]); dom = np.array(["synth2"] * len(ys) + ["packs"] * len(yp) + ["corpus"] * len(yc) + ["vec"] * len(y))
pa = cross_val_predict(make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)), Xa, ya, cv=cv)
per = {d: round(float((pa[dom == d] == ya[dom == d]).mean()), 3) for d in ("synth2", "packs", "corpus", "vec")}
print("all four domains, 5-fold, accuracy per domain:", per)
prev = json.load(open(ROOT / "out" / "classifier_union3.json"))["results"]
better = per["packs"] * 100 >= prev["all_on_packs"] - 1 and per["vec"] > acc
if better:
    full = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)).fit(Xa, ya); sc, lr = full.named_steps["standardscaler"], full.named_steps["logisticregression"]
    model = dict(features=FEATS, mean=sc.mean_.round(6).tolist(), scale=sc.scale_.round(6).tolist(), weights=lr.coef_.round(6).tolist(), bias=lr.intercept_.round(6).tolist(), classes=list(lr.classes_))
    json.dump(dict(model=model, per_domain=per, trained_on=dict(synth2=int(len(ys)), packs=int(len(yp)), corpus=int(len(yc)), vec=int(len(y)))), open(ROOT / "out" / "classifier_union4.json", "w"), indent=1)
    print("exported out/classifier_union4.json (meter model.json not replaced automatically)")
json.dump(dict(n=int(len(y)), meter_acc=acc, meter_recall=rec, calls=conf, all_domains=per, exported=bool(better)), open(Path(sys.argv[1]).with_name("pack-eval.json"), "w"), indent=1)
