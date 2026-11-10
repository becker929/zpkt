#!/usr/bin/env python3
"""Stage 1: which few measures name the role?

    python3 analysis/classify.py out/library_synth.csv [out/library_real.csv] -o out/classifier.json

Reads hit-feature CSVs with a role label (the file name's first token, e.g.
kick__lib__0001), drops non-numeric and leaky columns, and:
  1. scores the full feature set with a small tree ensemble, 5-fold CV
  2. forward-selects features with a plain logistic regression on
     standardised inputs, stopping when the gain is under 0.5 points,
     reporting accuracy after each added measure
  3. reports the confusion between roles at the chosen size
  4. if a second CSV (real sounds) is given, trains on synth and tests on
     real, and also on the union with grouped CV (group = source)
  5. exports the chosen logistic model (means, scales, weights, bias, classes)
     as JSON so a browser tool can run it
"""
import argparse, csv, json, math, sys
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict, cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import confusion_matrix

DROP = {"file", "sound", "param", "value", "duration_s", "peak_db", "rms_db", "loudness_a_db"}   # duration/level are set by us, not by the role
# measures a browser can compute from raw samples in a few lines: no pitch tracker, no HPSS
PORTABLE = {"rise_10_90_ms", "attack_ms", "decay20_ms", "decay40_ms", "sustain_share", "t60_estimate_ms", "crest_factor_db", "zero_crossing_rate",
            "spectral_centroid_hz", "spectral_centroid_hz_100ms", "centroid_slope_hz_per_ms", "spectral_flatness", "spectral_rolloff_85", "spectral_bandwidth",
            "band_sub_share", "band_low_share", "band_lowmid_share", "band_mid_share", "band_high_share", "band_air_share"}
ROLE_OF = {"hat_closed": "hat", "hat_open": "hat", "perc": "hook", "stab": "hook", "pad": "space", "riser": "space", "impact": "space"}


def load(path, coarse):
    rows = list(csv.DictReader(open(path)))
    feats = sorted(k for k in rows[0] if k not in DROP)
    X, y, src, files = [], [], [], []
    for r in rows:
        files.append(r["file"])
        lab = r["sound"] or r["file"].rsplit("/", 1)[-1].split("__")[0]
        y.append(ROLE_OF.get(lab, lab) if coarse else lab)
        X.append([float(r[k]) if r[k] not in ("", "nan") else np.nan for k in feats])
        src.append(r["file"].split("__")[1] if "__" in r["file"] else "x")
    X = np.array(X, dtype=float)
    # a NaN pitch means "no pitch found"; encode as a flag plus the column median
    for j, k in enumerate(feats):
        col = X[:, j]; bad = ~np.isfinite(col)
        if bad.any():
            med = np.nanmedian(col) if np.isfinite(col).any() else 0.0
            X[bad, j] = med
    return X, np.array(y), feats, files


def logit():
    return make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000))


def forward(X, y, feats, cv, min_gain=0.005, max_k=8):
    chosen, hist, best = [], [], 0.0
    while len(chosen) < max_k:
        cand = None
        for j in range(X.shape[1]):
            if j in chosen: continue
            acc = cross_val_score(logit(), X[:, chosen + [j]], y, cv=cv).mean()
            if cand is None or acc > cand[0]: cand = (acc, j)
        if cand[0] - best < min_gain and chosen: break
        best = cand[0]; chosen.append(cand[1]); hist.append((feats[cand[1]], round(best, 4)))
        print(f"  + {feats[cand[1]]:32s} -> {best:.3f}", file=sys.stderr)
    return chosen, hist


def export(model, feats, chosen, classes):
    sc, lr = model.named_steps["standardscaler"], model.named_steps["logisticregression"]
    return dict(features=[feats[j] for j in chosen], mean=sc.mean_.tolist(), scale=sc.scale_.tolist(),
                weights=lr.coef_.tolist(), bias=lr.intercept_.tolist(), classes=list(classes))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("synth"); ap.add_argument("real", nargs="?"); ap.add_argument("-o", default="out/classifier.json")
    ap.add_argument("--fine", action="store_true", help="10 fine labels instead of the 6 jobs")
    ap.add_argument("--portable", action="store_true", help="only measures a browser tool can compute")
    ap.add_argument("--max-k", type=int, default=8, help="most measures the forward selection may keep")
    a = ap.parse_args()
    X, y, feats, files = load(a.synth, not a.fine)
    if a.portable:
        keep = [j for j, f in enumerate(feats) if f in PORTABLE]
        X, feats = X[:, keep], [feats[j] for j in keep]
    cv = StratifiedKFold(5, shuffle=True, random_state=0)
    rf = RandomForestClassifier(300, random_state=0)
    full = cross_val_score(rf, X, y, cv=cv).mean()
    print(f"all {len(feats)} measures, forest: {full:.3f}", file=sys.stderr)
    rf.fit(X, y); imp = sorted(zip(rf.feature_importances_, feats), reverse=True)[:12]
    chosen, hist = forward(X, y, feats, cv, max_k=a.max_k)
    pred = cross_val_predict(logit(), X[:, chosen], y, cv=cv)
    classes = sorted(set(y)); cm = confusion_matrix(y, pred, labels=classes)
    res = dict(n=len(y), n_features=len(feats), forest_all=round(full, 4), importance=[(f, round(float(i), 4)) for i, f in imp],
               forward=hist, chosen=[feats[j] for j in chosen], classes=classes, confusion=cm.tolist(),
               recall={c: round(float((pred[y == c] == c).mean()), 3) for c in classes})
    # when the set mixes synthetic and real files, score each domain on its own
    dom = np.array(["real" if "__real__" in r else "synth" for r in files])
    res["by_domain"] = {d: dict(n=int((dom == d).sum()), acc=round(float((pred[dom == d] == y[dom == d]).mean()), 4),
                                recall={c: round(float((pred[(dom == d) & (y == c)] == c).mean()), 3) for c in classes if ((dom == d) & (y == c)).any()})
                        for d in sorted(set(dom))}
    for d, v in res["by_domain"].items(): print(f"  {d}: n={v['n']} acc={v['acc']} recall={v['recall']}", file=sys.stderr)
    if a.real:
        Xr, yr, fr, _ = load(a.real, not a.fine)
        Xr = Xr[:, [fr.index(f) for f in feats]]
        m = logit().fit(X[:, chosen], y); acc_real = float((m.predict(Xr[:, chosen]) == yr).mean())
        m_all = RandomForestClassifier(300, random_state=0).fit(X, y); acc_real_all = float((m_all.predict(Xr) == yr).mean())
        Xu, yu = np.vstack([X, Xr]), np.concatenate([y, yr])
        acc_union = cross_val_score(logit(), Xu[:, chosen], yu, cv=cv).mean()
        cmr = confusion_matrix(yr, m.predict(Xr[:, chosen]), labels=classes)
        res.update(real_n=len(yr), synth_to_real=round(acc_real, 4), synth_to_real_all_features=round(acc_real_all, 4),
                   union_cv=round(float(acc_union), 4), real_confusion=cmr.tolist(), real_classes_present=sorted(set(yr)))
        print(f"synth->real: {acc_real:.3f} (chosen), {acc_real_all:.3f} (forest, all)  union cv {acc_union:.3f}", file=sys.stderr)
        final = logit().fit(Xu[:, chosen], yu)
    else:
        final = logit().fit(X[:, chosen], y)
    res["model"] = export(final, feats, chosen, final.named_steps["logisticregression"].classes_)
    json.dump(res, open(a.o, "w"), indent=1)
    print(f"wrote {a.o}", file=sys.stderr)


if __name__ == "__main__":
    main()
