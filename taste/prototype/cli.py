"""
taste CLI — entrypoint for all corpus and analysis operations.

Usage:
    uv run taste analyze <audio_path>
    uv run taste judge <audio_path>
    uv run taste corpus add <audio_path> --verdict 4 --notes "..."
    uv run taste corpus stats
    uv run taste corpus search <query>
    uv run taste eval
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich import print as rprint

app = typer.Typer(name="taste", help="Scaling Taste — audio perception and evaluation CLI.")
corpus_app = typer.Typer(help="Corpus management commands.")
app.add_typer(corpus_app, name="corpus")

console = Console()


def _get_store():
    from .corpus.store import CorpusStore
    return CorpusStore()


# ── analyze ──────────────────────────────────────────────────────────────────

@app.command()
def analyze(
    audio_path: str = typer.Argument(..., help="Path to audio file (WAV or MP3)."),
    no_pitch: bool = typer.Option(False, "--no-pitch", help="Skip basic-pitch (faster)."),
    no_embeddings: bool = typer.Option(False, "--no-embeddings", help="Skip DCLAP embedding."),
    describe: bool = typer.Option(False, "--describe", help="Generate LLM description."),
    describer: str = typer.Option(
        "llm", "--describer",
        help="Describer to use: 'llm' (Claude Haiku, default) or 'gemini' (Phase 2 audio-LM).",
    ),
    json_out: bool = typer.Option(False, "--json", help="Output raw JSON."),
):
    """Run the audio perception pipeline and print the AudioProfile."""
    from .audio.analyzer import analyze as _analyze
    from .audio import describer as desc_mod

    path = Path(audio_path)
    if not path.exists():
        rprint(f"[red]File not found: {audio_path}[/red]")
        raise typer.Exit(1)

    console.print(f"[cyan]Analyzing:[/cyan] {path.name}")
    with console.status("Running extractors..."):
        profile = _analyze(
            str(path),
            run_pitch=not no_pitch,
            run_embeddings=not no_embeddings,
        )

    if describe:
        with console.status(f"Generating description ({describer})..."):
            if describer == "gemini":
                profile.description = desc_mod.describe_gemini(profile)
            else:
                profile.description = desc_mod.describe(profile)

    if json_out:
        import dataclasses
        print(json.dumps(dataclasses.asdict(profile), indent=2, default=str))
        return

    _print_profile(profile)

    # Cache the profile in the store
    store = _get_store()
    import dataclasses
    store.cache_profile(profile.clip_id, json.dumps(dataclasses.asdict(profile), default=str))
    console.print(f"\n[dim]clip_id: {profile.clip_id}[/dim]")

    if profile.errors:
        rprint(f"[yellow]Warnings:[/yellow] {', '.join(profile.errors)}")


# ── judge ─────────────────────────────────────────────────────────────────────

@app.command()
def judge(
    audio_path: str = typer.Argument(..., help="Path to audio file."),
    no_describe: bool = typer.Option(False, "--no-describe", help="Skip LLM description step."),
    describer: str = typer.Option(
        "llm", "--describer",
        help="Describer to use: 'llm' (Claude Haiku, default) or 'gemini' (Phase 2 audio-LM).",
    ),
    json_out: bool = typer.Option(False, "--json", help="Output raw JSON."),
):
    """Run full analysis + taste model judgment."""
    from .audio.analyzer import analyze as _analyze
    from .audio import describer as desc_mod
    from .judge.taste_model import TasteModel

    path = Path(audio_path)
    if not path.exists():
        rprint(f"[red]File not found: {audio_path}[/red]")
        raise typer.Exit(1)

    store = _get_store()
    stats = store.stats()
    if stats["total"] == 0:
        rprint("[yellow]Warning: corpus is empty. Add annotations first with 'taste corpus add'.[/yellow]")

    console.print(f"[cyan]Analyzing:[/cyan] {path.name}")
    with console.status("Running extractors..."):
        profile = _analyze(str(path))

    if not no_describe:
        with console.status(f"Generating description ({describer})..."):
            if describer == "gemini":
                profile.description = desc_mod.describe_gemini(profile)
            else:
                profile.description = desc_mod.describe(profile)

    with console.status(f"Querying taste model ({stats['total']} corpus entries)..."):
        model = TasteModel(store=store)
        verdict = model.judge(profile)

    if json_out:
        import dataclasses
        print(json.dumps(dataclasses.asdict(verdict), indent=2, default=str))
        return

    _print_verdict(verdict)

    if profile.errors:
        rprint(f"[yellow]Extraction warnings:[/yellow] {', '.join(profile.errors)}")


# ── corpus ────────────────────────────────────────────────────────────────────

@corpus_app.command("add")
def corpus_add(
    audio_path: str = typer.Argument(..., help="Path to audio file to annotate."),
    verdict: int = typer.Option(..., "--verdict", "-v", min=1, max=5, help="Score 1–5."),
    notes: str = typer.Option("", "--notes", "-n", help="Free-text notes."),
    what_works: str = typer.Option("", "--works", help="What works about this clip."),
    what_fails: str = typer.Option("", "--fails", help="What fails about this clip."),
    anchors: str = typer.Option("", "--anchors", help="Comparison anchors."),
    lens: str = typer.Option("overall", "--lens", help="Evaluation lens."),
    decomposition: str = typer.Option("full_mix", "--decomp", help="Decomposition type."),
    no_embeddings: bool = typer.Option(False, "--no-embeddings"),
):
    """Manually add an annotation to the corpus."""
    from .audio.analyzer import analyze as _analyze
    from .corpus.models import AnnotationEntry, EvaluationLens
    import dataclasses

    path = Path(audio_path)
    if not path.exists():
        rprint(f"[red]File not found: {audio_path}[/red]")
        raise typer.Exit(1)

    with console.status("Extracting audio profile..."):
        profile = _analyze(str(path), run_pitch=False, run_embeddings=not no_embeddings)

    store = _get_store()
    store.cache_profile(
        profile.clip_id,
        json.dumps(dataclasses.asdict(profile), default=str),
    )

    entry = AnnotationEntry(
        clip_id=profile.clip_id,
        source_track=path.name,
        time_range=(0.0, profile.duration_seconds),
        decomposition=decomposition,
        evaluation_lens=lens,
        verdict=verdict,
        what_works=what_works,
        what_fails=what_fails,
        comparison_anchors=anchors,
        notes=notes,
        embedding=profile.embedding,
    )

    row_id = store.add_annotation(entry)
    rprint(f"[green]Added annotation #{row_id}[/green] — "
           f"clip_id={entry.clip_id} verdict={verdict}/5")


@corpus_app.command("stats")
def corpus_stats():
    """Show corpus size, score distribution, and coverage."""
    store = _get_store()
    stats = store.stats()

    console.print(f"\n[bold]Corpus Statistics[/bold]  ({stats['total']} entries)\n")

    # Verdict distribution
    table = Table(title="Verdict Distribution")
    table.add_column("Score", justify="center")
    table.add_column("Count", justify="right")
    table.add_column("Bar", justify="left")
    total = stats["total"] or 1
    for score in range(1, 6):
        count = stats["by_verdict"].get(score, 0)
        bar = "█" * int(count / total * 30)
        table.add_row(f"{score}/5", str(count), f"[cyan]{bar}[/cyan]")
    console.print(table)

    # Source tag breakdown
    console.print("\n[bold]Source Tags:[/bold]")
    for tag, count in stats["by_source_tag"].items():
        pct = count / total * 100
        console.print(f"  {tag:<15} {count:>4} ({pct:.0f}%)")

    # Lens breakdown
    console.print("\n[bold]Evaluation Lenses:[/bold]")
    for lens, count in stats["by_evaluation_lens"].items():
        console.print(f"  {lens:<20} {count:>4}")


@corpus_app.command("search")
def corpus_search(
    query: str = typer.Argument(..., help="Text to search for in annotations."),
):
    """Full-text search over corpus annotations."""
    store = _get_store()
    results = store.search_text(query)
    if not results:
        rprint(f"[yellow]No results for '{query}'[/yellow]")
        return
    rprint(f"[green]{len(results)} result(s) for '{query}'[/green]\n")
    for e in results:
        rprint(f"  [bold]{e.clip_id}[/bold] ({e.source_track}) — verdict {e.verdict}/5")
        if e.what_works:
            rprint(f"    WORKS: {e.what_works}")
        if e.what_fails:
            rprint(f"    FAILS: {e.what_fails}")
        if e.notes:
            rprint(f"    NOTES: {e.notes}")
        rprint("")


# ── eval ──────────────────────────────────────────────────────────────────────

@app.command()
def eval(
    validation_split: float = typer.Option(
        0.2, "--split", help="Fraction of corpus to use as validation set."
    ),
    json_out: bool = typer.Option(False, "--json"),
):
    """Evaluate taste model against held-out corpus entries."""
    from .judge.taste_model import TasteModel
    import random

    store = _get_store()
    all_entries = store.get_all_annotations()
    if len(all_entries) < 5:
        rprint("[red]Need at least 5 corpus entries to run eval.[/red]")
        raise typer.Exit(1)

    # Hold out the most recent entries as validation
    random.seed(42)
    n_val = max(1, int(len(all_entries) * validation_split))
    val_entries = all_entries[-n_val:]

    console.print(f"Evaluating on {len(val_entries)} held-out entries...")
    model = TasteModel(store=store)
    results = model.eval_validation_set(val_entries)

    if json_out:
        print(json.dumps(results, indent=2, default=str))
        return

    console.print(f"\n[bold]Eval Results[/bold]")
    console.print(f"  Total entries:    {results['total']}")
    console.print(f"  Evaluated:        {results.get('evaluated', 0)}")
    agreement = results.get("agreement_within_1", 0)
    color = "green" if agreement >= 0.7 else "yellow" if agreement >= 0.5 else "red"
    console.print(f"  Agreement (±1):   [{color}]{agreement:.0%}[/{color}]  (target: 70%+)")
    if results.get("mean_score_diff") is not None:
        console.print(f"  Mean score diff:  {results['mean_score_diff']:.2f}")


# ── helpers ───────────────────────────────────────────────────────────────────

def _print_profile(profile):
    console.print(f"\n[bold]AudioProfile[/bold]  {profile.audio_path}")
    console.print(f"  Duration:   {profile.duration_seconds:.1f}s  |  SR: {profile.sample_rate} Hz")

    r = profile.rhythm
    if r and r.bpm:
        swing = f", swing {r.swing_ratio:.2f}" if r.swing_ratio else ""
        console.print(f"  Tempo:      {r.bpm:.1f} BPM  "
                      f"({len(r.beats)} beats, {r.meter_numerator}/4{swing})")
        console.print(f"  Groove:     {r.groove_density:.1f} onsets/beat  "
                      f"regularity std={r.beat_regularity:.3f}s")

    lo = profile.loudness
    if lo:
        lufs = f"{lo.lufs_integrated:.1f} LUFS" if lo.lufs_integrated is not None else "n/a"
        key = lo.camelot_key or "n/a"
        console.print(f"  Loudness:   {lufs}  |  Key: {key}")
        if lo.band_energy:
            be = lo.band_energy
            console.print(
                f"  Spectrum:   sub={be.get('sub',0):.0%}  low={be.get('low',0):.0%}  "
                f"mid={be.get('mid',0):.0%}  high={be.get('high',0):.0%}  "
                f"air={be.get('air',0):.0%}"
            )

    sp = profile.spectral
    if sp:
        console.print(f"  Centroid:   {sp.spectral_centroid_mean:.0f} Hz  "
                      f"harmonic_ratio={sp.harmonic_ratio_mean:.2f}")
        if sp.key:
            console.print(f"  Est. key:   {sp.key} (strength {sp.key_strength:.2f})")

    pi = profile.pitch
    if pi and pi.note_count > 0:
        console.print(f"  Pitch:      {pi.note_count} notes  "
                      f"range {pi.pitch_range_semitones} semitones  "
                      f"polyphony {pi.polyphony_mean:.1f}")

    if profile.embedding:
        console.print(f"  Embedding:  512-dim DCLAP  ✓")

    if profile.description:
        console.print(f"\n[italic]{profile.description}[/italic]")


def _print_verdict(verdict):
    score_colors = {1: "red", 2: "red", 3: "yellow", 4: "green", 5: "bold green"}
    color = score_colors.get(verdict.score, "white")
    conf_color = "green" if verdict.confidence >= 0.7 else "yellow" if verdict.confidence >= 0.5 else "red"

    console.print(f"\n[bold]Taste Model Verdict[/bold]")
    console.print(f"  Score:      [{color}]{verdict.score}/5[/{color}]  "
                  f"confidence [{conf_color}]{verdict.confidence:.0%}[/{conf_color}]")
    if verdict.low_confidence_reason:
        console.print(f"  [yellow]Low confidence: {verdict.low_confidence_reason}[/yellow]")
    console.print(f"\n  [bold]Rationale:[/bold]")
    console.print(f"  {verdict.rationale}")
    if verdict.suggestions:
        console.print(f"\n  [bold]Suggestions:[/bold]")
        for s in verdict.suggestions:
            console.print(f"    • {s}")
    console.print(f"\n  [dim]Retrieved {len(verdict.retrieved_ids)} entries  "
                  f"({verdict.elapsed_seconds:.1f}s)[/dim]")


def main():
    app()


if __name__ == "__main__":
    main()
