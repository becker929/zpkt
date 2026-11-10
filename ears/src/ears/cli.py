"""ears CLI — analyze audio files and emit AudioProfile JSON."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="ears", help="ears: measure a render. Loudness, true peak, spectra, embeddings, your corpus.")
corpus_app = typer.Typer(help="Your reference corpus: build it once from a folder, then place renders in it.")
app.add_typer(corpus_app, name="corpus")
console = Console()
err_console = Console(stderr=True)


@app.command()
def analyze(
    audio_path: str = typer.Argument(..., help="Path to audio file (WAV or MP3)."),
    no_embeddings: bool = typer.Option(False, "--no-embeddings", help="Skip DCLAP embedding."),
    rhythm: bool = typer.Option(False, "--rhythm", help="Run madmom beat tracking (optional dep)."),
    pitch: bool = typer.Option(False, "--pitch", help="Run basic-pitch (optional dep, slow)."),
    json_out: bool = typer.Option(False, "--json", help="Output raw JSON to stdout."),
) -> None:
    """Run the audio perception pipeline and print the AudioProfile."""
    from .analyzer import analyze as _analyze

    path = Path(audio_path)
    if not path.exists():
        err_console.print(f"[red]File not found: {audio_path}[/red]")
        raise typer.Exit(1)

    if not json_out:
        console.print(f"[cyan]Analyzing:[/cyan] {path.name}")

    profile = _analyze(
        str(path),
        run_embeddings=not no_embeddings,
        run_rhythm=rhythm,
        run_pitch=pitch,
    )

    if json_out:
        print(json.dumps(dataclasses.asdict(profile), default=_json_default))
        return

    # Human-readable rich output
    console.print(f"\n[bold]AudioProfile[/bold] — {path.name}")
    console.print(f"  Duration:  {profile.duration_seconds:.2f}s  |  SR: {profile.sample_rate} Hz")
    console.print(f"  clip_id:   {profile.clip_id}")

    if profile.loudness:
        ld = profile.loudness
        console.print(f"\n[bold]Loudness[/bold]")
        def _row(label: str, value: float | None, unit: str) -> None:
            text = f"{value:.2f} {unit}" if value is not None else "n/a"
            console.print(f"  {label:<18} {text}")
        _row("LUFS integrated:", ld.lufs_integrated, "LUFS")
        _row("LUFS short-term:", ld.lufs_short_term_peak, "LUFS")
        _row("LUFS momentary:", ld.lufs_momentary_max, "LUFS")
        _row("True peak:", ld.true_peak_db, "dBTP")
        if ld.camelot_key:
            console.print(f"  Key (Camelot):     {ld.camelot_key}")
        if ld.band_energy:
            t = Table(show_header=True, header_style="dim", box=None, padding=(0, 1))
            t.add_column("Band", style="dim")
            t.add_column("Energy %", justify="right")
            for band, energy in ld.band_energy.items():
                t.add_row(band, f"{energy * 100:.1f}%")
            console.print(t)

    if profile.spectral:
        sp = profile.spectral
        console.print(f"\n[bold]Spectral[/bold]")
        console.print(f"  Centroid:   {sp.spectral_centroid_mean:.1f} Hz")
        console.print(f"  Rolloff:    {sp.spectral_rolloff_mean:.1f} Hz")
        console.print(f"  Flatness:   {sp.spectral_flatness_mean:.4f}")
        console.print(f"  Onset str:  {sp.onset_strength_mean:.3f}")
        if sp.key:
            console.print(f"  Key:        {sp.key} (strength {sp.key_strength:.2f})")
        if sp.danceability is not None:
            console.print(f"  Danceability: {sp.danceability:.3f}")

    if profile.rhythm:
        ry = profile.rhythm
        console.print(f"\n[bold]Rhythm[/bold]")
        console.print(f"  BPM:        {ry.bpm:.1f}" if ry.bpm else "  BPM:   n/a")
        console.print(f"  Meter:      {ry.meter_numerator}/4")
        if ry.swing_ratio is not None:
            console.print(f"  Swing:      {ry.swing_ratio:.3f}")

    if profile.embedding:
        console.print(f"\n[bold]Embedding[/bold]  {len(profile.embedding)}-dim DCLAP vector (first 4): "
                      f"{profile.embedding[:4]}")

    if profile.errors:
        console.print(f"\n[yellow]Errors:[/yellow] {', '.join(profile.errors)}")


@app.command()
def compare(
    file_a: str = typer.Argument(...),
    file_b: str = typer.Argument(...),
    no_embeddings: bool = typer.Option(False, "--no-embeddings"),
) -> None:
    """Compare two audio files and print a similarity report."""
    from .analyzer import analyze as _analyze
    from .similarity import compare as _compare

    console.print(f"[cyan]Analyzing A:[/cyan] {file_a}")
    a = _analyze(file_a, run_embeddings=not no_embeddings)
    console.print(f"[cyan]Analyzing B:[/cyan] {file_b}")
    b = _analyze(file_b, run_embeddings=not no_embeddings)

    console.print("\n[bold]Comparison[/bold]")

    if a.loudness and b.loudness:
        diff = (a.loudness.lufs_integrated or 0) - (b.loudness.lufs_integrated or 0)
        console.print(f"  LUFS delta:         {diff:+.2f} dB  (A vs B)")

    if a.spectral and b.spectral:
        diff = a.spectral.spectral_centroid_mean - b.spectral.spectral_centroid_mean
        console.print(f"  Centroid delta:     {diff:+.1f} Hz")

    result = _compare(a, b)
    if result.embedding_cosine is not None:
        console.print(f"  DCLAP cosine sim:   {result.embedding_cosine:.4f}  (1.0 = identical)")
    else:
        console.print("  DCLAP cosine sim:   n/a (no embeddings)")
    for p in (a, b):
        if p.errors:
            console.print(f"  [yellow]{Path(p.audio_path).name}:[/yellow] {', '.join(p.errors)}")


@corpus_app.command("build")
def corpus_build(
    folder: Path = typer.Argument(..., help="Folder of reference tracks (searched recursively)."),
    out: Path = typer.Option(None, "--out", help="Corpus file to write (default $EARS_CORPUS, else ~/.cache/zpkt/corpus.json)."),
    no_embeddings: bool = typer.Option(False, "--no-embeddings", help="Skip DCLAP embeddings."),
) -> None:
    """Measure every track in FOLDER once and write the corpus file."""
    from . import corpus as _corpus

    if not folder.is_dir():
        err_console.print(f"[red]Not a folder: {folder}[/red]")
        raise typer.Exit(1)

    def progress(i: int, n: int, path: Path) -> None:
        err_console.print(f"[dim]{i + 1}/{n}[/dim] {path.name}")

    try:
        built = _corpus.build(folder, embeddings=not no_embeddings, progress=progress)
    except ValueError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    path = _corpus.save(built, out or _corpus.default_path())
    with_vectors = sum(1 for t in built["tracks"] if t.get("embedding"))
    console.print(f"{len(built['tracks'])} tracks ({with_vectors} with embeddings, {len(built['skipped'])} skipped) -> {path}")
    if not no_embeddings and not with_vectors:
        console.print("[yellow]No embeddings: set EARS_DCLAP_MODEL (see the README). Measures still work.[/yellow]")


@corpus_app.command("distance")
def corpus_distance(
    audio_path: Path = typer.Argument(..., help="The render to place in the corpus."),
    corpus_path: Path = typer.Option(None, "--corpus", help="Corpus file (default $EARS_CORPUS, else ~/.cache/zpkt/corpus.json)."),
    no_embeddings: bool = typer.Option(False, "--no-embeddings", help="Skip DCLAP embedding."),
    json_out: bool = typer.Option(False, "--json", help="Output raw JSON to stdout."),
) -> None:
    """Place a render in your corpus: each measure against the corpus's range, and the nearest tracks."""
    from . import corpus as _corpus
    from .analyzer import analyze as _analyze

    if not audio_path.exists():
        err_console.print(f"[red]File not found: {audio_path}[/red]")
        raise typer.Exit(1)
    try:
        loaded = _corpus.load(corpus_path)
    except (FileNotFoundError, ValueError) as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    profile = _analyze(str(audio_path), run_embeddings=not no_embeddings)
    result = _corpus.distance(profile, loaded)
    if json_out:
        print(json.dumps(result))
        return
    console.print(f"[bold]{audio_path.name}[/bold] against {result['corpus_tracks']} corpus tracks")
    t = Table(show_header=True, header_style="dim", box=None, padding=(0, 1))
    for col in ("Measure", "Yours", "Median", "p10", "p90", "z"):
        t.add_column(col, justify="left" if col == "Measure" else "right")
    for name, m in result["measures"].items():
        z = "n/a" if m["z"] is None else f"{m['z']:+.1f}"
        style = None if m["inside"] else "yellow"
        t.add_row(name, f"{m['value']:.3g}", f"{m['median']:.3g}", f"{m['p10']:.3g}", f"{m['p90']:.3g}", z, style=style)
    console.print(t)
    console.print("[dim]Yellow rows are outside the corpus's 10th to 90th percentile.[/dim]")
    emb = result["embedding"]
    if emb:
        console.print(f"\nEmbedding: {emb['to_centre']:.3f} to the corpus centre "
                      f"(corpus tracks: median {emb['corpus_median']:.3f}, 10th percentile {emb['corpus_p10']:.3f})")
        for near in emb["nearest"]:
            console.print(f"  {near['cosine']:.3f}  {near['path']}")
    else:
        console.print("\n[dim]No embedding distance (set EARS_DCLAP_MODEL and rebuild the corpus to get it).[/dim]")
    if profile.errors:
        console.print(f"\n[yellow]Errors:[/yellow] {', '.join(profile.errors)}")


def _json_default(obj):
    try:
        return float(obj)
    except Exception:
        return str(obj)


def main():
    app()


if __name__ == "__main__":
    main()
