"""Score the seven steps from what a project folder shows. Each scorer returns (percent, evidence).

The rules are points with caps, so every percent can be read back from its evidence lines. They see
files, not sound: kick, mix and master stop at 80 %, arrange at 90 %, release at 60 %
(workflow.STEPS caps). The rest takes a record (hands.library.records).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from hands.library import workflow
from hands.library.facts import SetFacts, Track

KICK = re.compile(r"kick|\bkik\b|\bbd\b|bassdrum|bass ?drum", re.I)
RUMBLE = re.compile(r"rumble|rmbl|\bsub\b", re.I)
HATS = re.compile(r"hi-?hats?|\bhats?\b|\bhh\b|\b[oc]hh?\b|\bride\b|cymbal|crash|splash|shaker", re.I)
PERC = re.compile(r"perc|clap|snare|\brim|\btoms?\b|conga|bongo|clave|cowbell|snap", re.I)
PROCESSED = re.compile(r"/Samples/(Processed|Recorded)/|consolidat|freeze|resampl|/crop/|/reverse/", re.I)
LIMITER = re.compile(r"^(Limiter|GlueCompressor|Compressor2|MultibandDynamics)$|limit|clip|maxim|pro-l|ozone|\bl2\b|smash",
                     re.I)
METER = re.compile(r"span|spectrum|meter|tuner|youlean|insight|reastream|stream send|^StereoGain$|^Tuner$", re.I)
SILENT_SEND = 0.001  # Live stores a send at -inf as about 0.0003


@dataclass
class Export:
    """An audio or video file that looks like a render of the track."""
    path: Path
    size: int
    mtime: float
    kind: str  # master | mix | release | render
    seconds: float | None = None
    lufs: float | None = None
    true_peak: float | None = None


@dataclass
class Project:
    name: str
    folder: Path | None
    sets: list[SetFacts] = field(default_factory=list)  # newest first
    exports: list[Export] = field(default_factory=list)
    browser: dict | None = None    # its audio-browser project document, if any
    forked_from: dict[str, int] = field(default_factory=dict)  # other project -> samples used from its folder

    @property
    def current(self) -> SetFacts | None:
        return self.sets[0] if self.sets else None


def sample_words(path: str) -> str:
    """The file name and its folder, the part of a sample path that says what it is."""
    parts = path.replace("\\", "/").split("/")
    return " ".join(parts[-2:])


def roles(s: SetFacts, t: Track) -> set[str]:
    """What a track plays: kick, rumble, hats, perc (from its name, its groups' names and its rack samples)."""
    words = [t.name] + [g.name for g in s.groups_of(t)]
    if t.kind == "midi":
        words += [sample_words(p) for p in t.rack_samples]
    if t.kind == "audio":
        words += [sample_words(c.sample) for c in t.clips[:3] if c.sample]
    out = set()
    for w in words:
        out |= {r for r, rx in (("kick", KICK), ("rumble", RUMBLE), ("hats", HATS), ("perc", PERC)) if rx.search(w)}
    return out


def pct(points: float, cap: int) -> int:
    return int(max(0, min(cap, round(points))))


# --------------------------------------------------------------------------- I. collage

def collage(p: Project) -> tuple[int, list[str]]:
    """Sounds from the library cut, resampled and laid out: distinct audio files in clips on the music's
    non-drum tracks (10 each, up to 50), any resampled or consolidated file 20, audio clips on the timeline
    (2.5 each, up to 20), and those clips covering at least 16 bars 10. An audio-browser project of the
    same name counts too."""
    ev: list[str] = []
    points = 0.0
    s = p.current
    if s is not None:
        tracks = [t for t in s.content_tracks() if t.kind == "audio" and not roles(s, t) & {"kick", "rumble", "hats"}]
        clips = [c for t in tracks for c in t.clips]
        sources = {c.sample for c in clips if c.sample}
        processed = {x for x in sources if PROCESSED.search(x)}
        if sessions := sum(t.session_clips for t in tracks):
            ev.append(f"{sessions} audio clips in session slots")
        bars = (max((c.end for c in clips), default=0) - min((c.start for c in clips), default=0)) / 4
        points = min(50, 10 * len(sources)) + (20 if processed else 0) + min(20, 2.5 * len(clips)) + (10 if bars >= 16 else 0)
        ev.append(f"{len(sources)} distinct audio files in {len(clips)} timeline clips over {bars:.0f} bars "
                  f"on {len(tracks)} non-drum audio tracks")
        if processed:
            ev.append(f"{len(processed)} resampled or consolidated: " + ", ".join(sorted(Path(x).name for x in processed)[:3]))
        if not sources:
            ev.append("no audio clips outside the drums: nothing collaged yet")
    if p.browser:
        b = p.browser
        regions = len((b.get("collage") or {}).get("regions") or [])
        sounds = len(b.get("sounds") or [])
        if b.get("column") == "collage":
            browser_points = 40 + min(40, 10 * regions)
        else:
            browser_points = 10 + min(20, 2 * sounds)
        ev.append(f"audio-browser project {b.get('id')}: column {b.get('column')}, {sounds} sounds taken, "
                  f"{regions} collage regions" + (", abandoned" if b.get("abandoned") else ""))
        points = max(points, browser_points)
    return pct(points, workflow.BY_KEY["collage"].cap), ev


# --------------------------------------------------------------------------- II. drums

def drums(p: Project) -> tuple[int, list[str]]:
    """Kick 30, rumble 15, hats 25, other percussion 15, and drum tracks playing across at least 16 bars of
    the timeline 15 (session clips only: 5)."""
    s = p.current
    if s is None:
        return 0, ["no Live set"]
    found: dict[str, list[str]] = {"kick": [], "rumble": [], "hats": [], "perc": []}
    drum_tracks = []
    for t in s.content_tracks():
        r = roles(s, t)
        for role in r:
            found[role].append(t.name)
        if r:
            drum_tracks.append(t)
    points = 0
    for role, weight in (("kick", 30), ("rumble", 15), ("hats", 25), ("perc", 15)):
        if found[role]:
            points += weight
    ev = [f"{role}: " + (", ".join(sorted(set(names))[:4]) if names else "none found") for role, names in found.items()]
    beats = max((c.end for t in drum_tracks for c in t.clips), default=0) - min(
        (c.start for t in drum_tracks for c in t.clips), default=0)
    if beats >= 64:
        points += 15
        ev.append(f"drums play across {beats / 4:.0f} bars of the timeline")
    elif any(t.session_clips for t in drum_tracks):
        points += 5
        ev.append("drum patterns in session slots only")
    return pct(points, workflow.BY_KEY["drums"].cap), ev


# --------------------------------------------------------------------------- III. arrange

def sections(s: SetFacts, block: float = 16.0) -> int:
    """Sections on the timeline: runs of 4-bar blocks that play the same tracks, or the named locators
    inside the music, whichever is more."""
    start, end = s.span()
    tracks = s.content_tracks()
    runs, last = 0, None
    b = start
    while b < end:
        active = frozenset(t.id or t.name for t in tracks if any(c.start < b + block and c.end > b for c in t.clips))
        if active != last:
            runs += 1
            last = active
        b += block
    locs = sum(1 for time, _ in s.locators if start <= time < end)
    return max(runs, locs)


def arrange_one(s: SetFacts) -> tuple[int, str]:
    """One set: nothing on the timeline 0 (session clips 10), a loop under 16 bars 20, one or two sections 35,
    shorter than a Short 40, longer than a Short 60, near Short length 75, Short length (33-50 s) 90."""
    start, end = s.span()
    beats = end - start
    secs = s.seconds(beats)
    if beats <= 0:
        sess = sum(t.session_clips for t in s.content_tracks())
        return (10, f"{s.path.name}: {sess} session clips, nothing on the timeline") if sess else (
            0, f"{s.path.name}: no clips")
    n = sections(s)
    head = f"{s.path.name}: {beats / 4:.0f} bars, {secs:.0f} s at {s.tempo:g} BPM, {n} sections"
    if beats < 64:
        return 20, head + ": a loop on the timeline"
    if n < 3:
        return 35, head + ": not yet an arc"
    lo, hi = workflow.SHORT_S
    if lo <= secs <= hi:
        return 90, head + ": Short length"
    if workflow.NEAR_SHORT_S[0] <= secs <= workflow.NEAR_SHORT_S[1]:
        return 75, head + ": near Short length"
    if secs > hi:
        return 60, head + ": longer than a Short, which is not cut yet"
    return 40, head + ": shorter than a Short"


def arrange(p: Project) -> tuple[int, list[str]]:
    """The best arrangement among the project's sets (the Short may be cut in its own set)."""
    if not p.sets:
        return 0, ["no Live set"]
    scored = [(*arrange_one(s), i) for i, s in enumerate(p.sets)]
    best = max(scored, key=lambda x: (x[0], -x[2]))
    ev = [best[1]]
    if best[2] != 0:
        ev.append("newest set: " + scored[0][1])
    return pct(best[0], workflow.BY_KEY["arrange"].cap), ev


# --------------------------------------------------------------------------- IV. kick

def kick(p: Project) -> tuple[int, list[str]]:
    """A dedicated kick track or kick group 20 (kick only inside a shared drum rack: 10), processing devices on
    the kick, its rumble and its group 10 each up to 40, automation on them 10, sets named for kick work 10."""
    s = p.current
    if s is None:
        return 0, ["no Live set"]
    tracks = s.content_tracks()
    kicks = [t for t in tracks if "kick" in roles(s, t)]
    if not kicks:
        return 0, ["no kick track found"]
    dedicated = [t for t in tracks if roles(s, t) and roles(s, t) <= {"kick", "rumble"}]
    ev = []
    points = 0
    if any(t in kicks for t in dedicated):
        points += 20
        groups = {g.id: g for t in dedicated for g in s.groups_of(t)[:1] if KICK.search(g.name)}
        chain = dedicated + list(groups.values())
        ev.append("kick chain: " + ", ".join(t.name for t in chain))
    else:
        points += 10
        chain = kicks
        ev.append("kick shares a drum rack with other sounds: " + ", ".join(t.name for t in kicks))
    effects = [d for t in chain for d in t.effects]
    points += min(40, 10 * len(effects))
    ev.append(f"{len(effects)} processing devices on it: " + (", ".join(effects[:8]) or "none"))
    if envs := sum(t.envelopes for t in chain):
        points += 10
        ev.append(f"{envs} automation envelopes on the kick chain")
    named = [x.path.stem for x in p.sets if KICK.search(x.path.stem)]
    if named:
        points += 10
        ev.append(f"{len(named)} sets named for kick work: " + ", ".join(named[:3]))
    return pct(points, workflow.BY_KEY["kick"].cap), ev


# --------------------------------------------------------------------------- V. mix

def mix(p: Project) -> tuple[int, list[str]]:
    """Groups with processing 10 each up to 30, returns fed by sends 15, levels set on the music's tracks up to
    20 (a Utility, a moved fader or automation), automation 2 per envelope up to 10, a mix render 15."""
    s = p.current
    ev: list[str] = []
    points = 0.0
    if s is not None:
        groups = [t for t in s.tracks if t.kind == "group" and not t.reference and t.effects]
        points += min(30, 10 * len(groups))
        ev.append(f"{len(groups)} groups with processing" + (": " + ", ".join(g.name for g in groups[:5]) if groups else ""))
        returns = [t for t in s.tracks if t.kind == "return" and t.effects]
        content = s.content_tracks()
        sending = [t for t in content + groups if any(v > SILENT_SEND for v in t.sends)]
        if returns and sending:
            points += 15
            ev.append(f"{len(returns)} returns with devices, fed by {len(sending)} tracks")
        else:
            ev.append("no send effects in use")
        level_set = [t for t in content if "StereoGain" in t.devices or abs(t.volume - 1.0) > 0.01 or t.envelopes]
        if content:
            points += 20 * len(level_set) / len(content)
            ev.append(f"levels set on {len(level_set)} of {len(content)} tracks (Utility, fader or automation)")
        envs = sum(t.envelopes for t in content + groups)
        points += min(10, 2 * envs)
        ev.append(f"{envs} automation envelopes on tracks and groups")
    renders = [e for e in p.exports if e.kind in ("mix", "render", "master", "release")]
    if renders:
        points += 15
        newest = max(renders, key=lambda e: e.mtime)
        ev.append(f"{len(renders)} renders, newest {newest.path.name}")
    else:
        ev.append("no mix render found")
    return pct(points, workflow.BY_KEY["mix"].cap), ev


# --------------------------------------------------------------------------- VI. master

def master(p: Project) -> tuple[int, list[str]]:
    """A limiter, clipper or bus compressor on Main 30, other processing on Main 10, a mastered export 30, and
    a measured master inside the Short's target (-14 to -11 LUFS, true peak at most -1 dBTP) 20."""
    s = p.current
    ev: list[str] = []
    points = 0
    if s is not None:
        fx = s.main.effects
        limiters = [d for d in fx if LIMITER.search(d)]
        other = [d for d in fx if d not in limiters and not METER.search(d)]
        if limiters:
            points += 30
        if other:
            points += 10
        ev.append("Main chain: " + (", ".join(fx) if fx else "empty"))
    masters = sorted((e for e in p.exports if e.kind in ("master", "release")), key=lambda e: -e.mtime)
    if masters:
        points += 30
        ev.append(f"{len(masters)} mastered exports, newest {masters[0].path.name}")
        measured = [e for e in masters if e.lufs is not None]
        if measured:
            e = measured[0]
            lufs = float(e.lufs or 0.0)
            lo, hi = workflow.MASTER_LUFS
            inside = lo <= lufs <= hi and (e.true_peak is None or e.true_peak <= workflow.MASTER_TP)
            if inside:
                points += 20
            ev.append(f"{e.path.name}: {lufs:.1f} LUFS, {e.true_peak or 0.0:.1f} dBTP "
                      + ("(inside the target)" if inside else f"(target {lo:g} to {hi:g} LUFS, <= {workflow.MASTER_TP:g} dBTP)"))
    else:
        ev.append("no mastered export found")
    return pct(points, workflow.BY_KEY["master"].cap), ev


# --------------------------------------------------------------------------- VII. release

def release(p: Project) -> tuple[int, list[str]]:
    """A release candidate (final, release, short or youtube in its name, or a video) 30, and a mastered
    candidate of Short length 30. Published takes a record with the link."""
    cands = sorted((e for e in p.exports if e.kind == "release"), key=lambda e: -e.mtime)
    if not cands:
        return 0, ["no final export or video found; not published (no release record)"]
    points = 30
    ev = [f"{len(cands)} release candidates, newest {cands[0].path.name}"]
    lo, hi = workflow.NEAR_SHORT_S
    if any(e.seconds and lo <= e.seconds <= hi for e in cands):
        points += 30
        ev.append("one is Short length")
    ev.append("not published (no release record)")
    return pct(points, workflow.BY_KEY["release"].cap), ev


SCORERS = {"collage": collage, "drums": drums, "arrange": arrange, "kick": kick,
           "mix": mix, "master": master, "release": release}
