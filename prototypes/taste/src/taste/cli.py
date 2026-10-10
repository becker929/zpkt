"""Typer CLI for the taste layer.

Commands:
    judge         — score a render from a pre-computed AudioProfile JSON
    judge-audio   — score a render directly from an audio file (calls ears CLI)
    loop          — run N autonomous taste cycles
    corpus        — manage the annotation corpus
    eval          — evaluate judge performance on a validation set
"""

from __future__ import annotations

import typer

app = typer.Typer(name="taste", help="Brain / taste model.")

corpus_app = typer.Typer(help="Corpus management commands.")
app.add_typer(corpus_app, name="corpus")


@app.command()
def judge(
    profile: str = typer.Argument(..., help="Path to AudioProfile JSON."),
    output: str = typer.Option("-", "--output", "-o"),
) -> None:
    """Score a render from a pre-computed AudioProfile JSON."""
    from taste.judge.taste_model import TasteModel

    profile_json = open(profile).read()
    model = TasteModel()
    verdict = model.judge(profile_json)
    data = verdict.model_dump_json(indent=2)
    if output == "-":
        typer.echo(data)
    else:
        with open(output, "w") as fh:
            fh.write(data)
        typer.echo(f"Written to {output}", err=True)


@app.command(name="judge-audio")
def judge_audio(
    audio: str = typer.Argument(..., help="Path to audio file."),
    ears_bin: str = typer.Option("ears", "--ears-bin"),
) -> None:
    """Score a render directly from audio (calls the ears CLI internally)."""
    import subprocess
    import json

    result = subprocess.run(
        [ears_bin, "analyze", audio, "--output", "-"],
        capture_output=True, text=True, check=True,
    )
    from taste.judge.taste_model import TasteModel
    verdict = TasteModel().judge(result.stdout.strip())
    typer.echo(verdict.model_dump_json(indent=2))



@corpus_app.command("stats")
def corpus_stats(
    db: str = typer.Option("data/corpus.db", "--db"),
) -> None:
    """Print corpus size and score distribution."""
    from taste.corpus.store import CorpusStore
    store = CorpusStore(db)
    total = store.count()
    typer.echo(f"Corpus: {total} annotations")
    if total:
        entries = store.all()
        from collections import Counter
        dist = Counter(e.score for e in entries)
        for score in sorted(dist):
            typer.echo(f"  {score}/5: {dist[score]}")


@corpus_app.command("add")
def corpus_add(
    clip_id: str = typer.Option(..., "--clip-id"),
    verdict: int = typer.Option(..., "--verdict", help="Score 1-5."),
    feedback: str = typer.Option("", "--feedback"),
    db: str = typer.Option("data/corpus.db", "--db"),
) -> None:
    """Add a verdict to the corpus."""
    typer.echo(f"[corpus add] clip_id={clip_id} verdict={verdict}")
    typer.echo("(Not yet fully implemented — wire up profile and render paths.)")


def main() -> None:
    app()
