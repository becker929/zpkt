"""A run's bookkeeping: its workspace and run.json, stage times, incidents, metrics, the verdict, and
the one line per run in runs.jsonl that later runs are compared against.

    run runlog.py init URL                       # workspace + run.json; exit 3 if already learned
    run runlog.py set ID --from-meta             # title, channel, video_s from the fetch's meta.json
    run runlog.py set ID technique bass-from-perc-loop
    run runlog.py stage ID scrape start
    run runlog.py stage ID scrape end --verifier-errors 3 --note "backbeat clap missed"
    run runlog.py incident ID practice dirty-set "HW002 set left dirty by a plan render"
    run runlog.py metric ID onset.render_max_ms 3.7
    run runlog.py verdict ID "Those sound really good" --date 2026-10-12
    run runlog.py retro ID                       # append/replace its runs.jsonl line, compare with earlier runs
    run runlog.py compare                        # every run, one row each

Workspace: ~/_agent_scratch/tutorials/<id>/ (--root). runs.jsonl sits beside SKILL.md in the
checkout this script is in, so run the retro from your own worktree. Incident kinds are the
section names of reference/recovery.md, plus "other". The retro takes the self-test bias from
W/preflight_scrape.json, and flags a regression when a stage takes over 1.5x its median over
earlier runs, verifier errors rise, the render onset error grows by more than 1 ms over the worst
earlier run, the self-test bias moves by more than 1 ms, or an incident kind repeats: each flag
means change a brief or a script (SKILL.md, Retro).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
REPO = SKILL.parents[2]
RUNS = SKILL / "runs.jsonl"
INDEX = REPO / "docs" / "techniques" / "README.md"
STAGES = ["intake", "preflight", "scrape", "practice", "deliver", "file", "retro"]
RECOVERY = SKILL / "reference" / "recovery.md"
KINDS = [m.group(1) for m in re.finditer(r"^## ([a-z-]+)\s*$", RECOVERY.read_text(), re.MULTILINE)] + ["other"]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def video_id(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    raise SystemExit(f"no YouTube video id in {url!r}")


def runs() -> list[dict]:
    return [json.loads(line) for line in RUNS.read_text().splitlines() if line.strip()] if RUNS.exists() else []


def path_for(root: str, vid: str) -> Path:
    return Path(root).expanduser() / vid / "run.json"


def load(a) -> tuple[Path, dict]:
    p = path_for(a.root, a.id)
    if not p.exists():
        raise SystemExit(f"no {p}: run `runlog.py init` first")
    return p, json.loads(p.read_text())


def save(p: Path, r: dict) -> None:
    p.write_text(json.dumps(r, indent=1, ensure_ascii=False) + "\n")


def init(a) -> None:
    vid = video_id(a.url)
    done = [r for r in runs() if r.get("id") == vid]
    in_index = INDEX.exists() and vid in INDEX.read_text()
    if (done or in_index) and not a.again:
        print(f"{vid} was learned already (runs.jsonl: {[r['run'] for r in done]}, index: {in_index}); "
              "open its card in docs/techniques/ instead, or pass --again for a deliberate re-run")
        sys.exit(3)
    p = path_for(a.root, vid)
    if p.exists():
        print(f"{p} exists: resuming it")
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    r = {"id": vid, "url": f"https://www.youtube.com/watch?v={vid}", "started": now(),
         "skill_commit": commit.stdout.strip() or None, "repeat_of": [x["run"] for x in done] or None,
         "stages": {s: {} for s in STAGES}, "incidents": [], "metrics": {}, "verdict": None, "published": None}
    r["stages"]["intake"] = {"start": r["started"]}
    save(p, r)
    print(f"workspace {p.parent}; run.json written")


TOP = {"title", "channel", "video_s", "technique", "published", "note"}


def set_(a) -> None:
    p, r = load(a)
    if a.from_meta:
        meta = json.loads((p.parent / "meta.json").read_text())
        r.update(title=meta.get("title"), channel=meta.get("channel"), video_s=meta.get("duration"))
    if a.key:
        if a.key not in TOP:
            raise SystemExit(f"key must be one of {sorted(TOP)}")
        try:
            r[a.key] = json.loads(a.value)
        except (TypeError, ValueError):
            r[a.key] = a.value
    save(p, r)
    print({k: r.get(k) for k in sorted(TOP)})


def stage(a) -> None:
    p, r = load(a)
    st = r["stages"].setdefault(a.stage, {})
    st[a.event] = now()
    if a.event == "end" and "start" in st:
        st["wall_min"] = round((datetime.fromisoformat(st["end"]) - datetime.fromisoformat(st["start"])).total_seconds()
                               / 60, 1)
    if a.verifier_errors is not None:
        st["verifier_errors"] = a.verifier_errors
    if a.note:
        st.setdefault("notes", []).append(a.note)
    save(p, r)
    print(f"{a.stage} {a.event}" + (f": {st['wall_min']} min" if a.event == "end" and "wall_min" in st else ""))


def incident(a) -> None:
    p, r = load(a)
    if a.kind not in KINDS:
        raise SystemExit(f"kind must be one of {KINDS} (recovery.md sections)")
    r["incidents"].append({"stage": a.stage, "kind": a.kind, "note": a.note, "at": now()})
    save(p, r)
    print(f"incident {a.kind} logged ({len(r['incidents'])} so far)")


def metric(a) -> None:
    p, r = load(a)
    try:
        value = json.loads(a.value)
    except ValueError:
        value = a.value
    d = r["metrics"]
    *head, last = a.key.split(".")
    for k in head:
        d = d.setdefault(k, {})
    d[last] = value
    save(p, r)
    print(f"{a.key} = {value!r}")


def verdict(a) -> None:
    p, r = load(a)
    r["verdict"] = {"text": a.text, "date": a.date or date.today().isoformat()}
    save(p, r)
    lines = runs()
    hit = [x for x in lines if x.get("id") == a.id and x.get("run") == r.get("run")]
    for line in hit:
        line["verdict"] = r["verdict"]
    if hit:
        RUNS.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines))
        print(f"verdict recorded in run.json and runs.jsonl (run {r['run']}): {r['verdict']}")
    else:
        print(f"verdict recorded in run.json only: no runs.jsonl line yet. Run `runlog.py retro {a.id}` "
              "(it carries the verdict over), or edit an older run's line by hand.")


def summary(r: dict, n: int) -> dict:
    return {"run": n, "id": r["id"], "date": r["started"][:10], "started": r["started"], "title": r.get("title"), "channel": r.get("channel"),
            "technique": r.get("technique"), "skill_commit": r.get("skill_commit"), "video_s": r.get("video_s"),
            "wall_min": {s: v["wall_min"] for s, v in r["stages"].items() if "wall_min" in v},
            "verifier_errors": {s: v["verifier_errors"] for s, v in r["stages"].items() if "verifier_errors" in v},
            "onset": r["metrics"].get("onset", {}), "metrics": {k: v for k, v in r["metrics"].items() if k != "onset"},
            "live_incidents": [i["kind"] for i in r["incidents"]], "published": r.get("published"),
            "verdict": r.get("verdict")}


def flags(this: dict, earlier: list[dict]) -> list[str]:
    out = []
    for s, m in this["wall_min"].items():
        past = [e["wall_min"][s] for e in earlier if s in e.get("wall_min", {})]
        if past and m > 1.5 * statistics.median(past):
            out.append(f"{s} took {m} min against a median of {statistics.median(past)}")
    for s, n in this["verifier_errors"].items():
        past = [e["verifier_errors"][s] for e in earlier if s in e.get("verifier_errors", {})]
        if past and n > min(past):
            out.append(f"{s} verifier found {n} errors (best earlier run: {min(past)})")
    v = this["onset"].get("render_max_ms")
    past = [abs(e["onset"]["render_max_ms"]) for e in earlier
            if isinstance(e.get("onset", {}).get("render_max_ms"), (int, float))]
    if isinstance(v, (int, float)) and past and abs(v) > max(past) + 1.0:
        out.append(f"render onset error {v} ms is over 1 ms worse than every earlier run (worst {max(past)})")
    v = this["onset"].get("selftest_bias_ms")
    past = [e["onset"]["selftest_bias_ms"] for e in earlier
            if isinstance(e.get("onset", {}).get("selftest_bias_ms"), (int, float))]
    if isinstance(v, (int, float)) and past and abs(v - statistics.median(past)) > 1.0:
        out.append(f"self-test bias moved to {v} ms (median of earlier runs {statistics.median(past)})")
    seen = {k for e in earlier for k in e.get("live_incidents", [])}
    out += [f"incident {k} again (seen in an earlier run)" for k in sorted(set(this["live_incidents"]) & seen)]
    return out


def retro(a) -> None:
    p, r = load(a)
    pf = p.parent / "preflight_scrape.json"
    if "selftest_bias_ms" not in r["metrics"].get("onset", {}) and pf.exists():
        st = next((x.get("value") for x in json.loads(pf.read_text())["results"] if x["check"] == "selftest"), None)
        if st:
            r["metrics"].setdefault("onset", {})["selftest_bias_ms"] = st["onset_bias_ms_worst"]
    lines = runs()
    old = next((x for x in lines if x.get("id") == r["id"] and x.get("started") == r["started"]), None)
    n = old["run"] if old else max([x["run"] for x in lines], default=0) + 1
    r["run"] = n
    this = summary(r, n)
    lines = [x for x in lines if x is not old] + [this]
    RUNS.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in sorted(lines, key=lambda x: x["run"])))
    save(p, r)
    earlier = [x for x in lines if x["run"] < n]
    print(f"run {n} -> {RUNS}")
    fl = flags(this, earlier)
    if not earlier:
        print("first run: nothing to compare against")
    for f in fl:
        print(f"REGRESSION: {f}")
    if earlier and not fl:
        print("no regression against earlier runs")


def compare(a) -> None:
    rows = runs()
    print(f"{'run':>3} {'id':12} {'date':10} {'scrape':>7} {'practice':>8} {'v.err s/p':>9} {'onset ms':>8}  incidents / verdict")
    for x in rows:
        w, v = x.get("wall_min", {}), x.get("verifier_errors", {})
        print(f"{x['run']:>3} {x['id']:12} {x['date']:10} {w.get('scrape', '-'):>7} {w.get('practice', '-'):>8} "
              f"{str(v.get('scrape', '-')) + '/' + str(v.get('practice', '-')):>9} "
              f"{x.get('onset', {}).get('render_max_ms', '-'):>8}  {len(x.get('live_incidents', []))} / "
              f"{(x.get('verdict') or {}).get('text', 'waiting')}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="~/_agent_scratch/tutorials")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("url")
    p.add_argument("--again", action="store_true")
    p = sub.add_parser("set")
    p.add_argument("id")
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.add_argument("--from-meta", action="store_true")
    p = sub.add_parser("stage")
    p.add_argument("id")
    p.add_argument("stage", choices=STAGES)
    p.add_argument("event", choices=["start", "end"])
    p.add_argument("--verifier-errors", type=int)
    p.add_argument("--note")
    p = sub.add_parser("incident")
    p.add_argument("id")
    p.add_argument("stage", choices=STAGES)
    p.add_argument("kind")
    p.add_argument("note")
    p = sub.add_parser("metric")
    p.add_argument("id")
    p.add_argument("key", help="dotted, e.g. onset.render_max_ms")
    p.add_argument("value", help="JSON or text")
    p = sub.add_parser("verdict")
    p.add_argument("id")
    p.add_argument("text")
    p.add_argument("--date")
    p = sub.add_parser("retro")
    p.add_argument("id")
    sub.add_parser("compare")
    a = ap.parse_args()
    {"init": init, "set": set_, "stage": stage, "incident": incident, "metric": metric, "verdict": verdict, "retro": retro,
     "compare": compare}[a.cmd](a)


if __name__ == "__main__":
    main()
