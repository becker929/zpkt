# Persona walkthrough

A cold agent plays a producer who makes a track through the zpkt app alone, and keeps a journal that the people
watching read as it is written (Anthony, 27 November 2026: "e2e GUI testing driven by a cold agent").

- **The persona** (`persona.md`): Ilan, a melodic techno producer, follows a recipe pieced together from tutorials.
  They have never seen zpkt. Their only window onto Live is the app in a browser, and the assistant in its Ask tab.
- **The tools** (`browser_mcp.py`): a stdio MCP server, Playwright only. A WebKit browser that may open only the app,
  read its accessibility tree, click, type, press, drag; a few screenshots per leg; a journal; a notebook the persona
  keeps across legs; checkpoints. The agent gets these tools and no others (no shell, no files).
- **Legs and checkpoints** (`run.py`): the recipe is cut into four legs. Each leg is a fresh `claude -p`. A checkpoint
  keeps the song as last saved in the app (its `.als`) and the notebook. A leg can start from any checkpoint: the song
  is copied under a new name, put in the app's song list and opened, so a scenario runs again from the middle.
- **The journal page** (`serve.py`, `page.html`): every run, newest first, filtered to the story, the findings and
  blockers, what worked, or everything with every click. Tailnet: `https://<mac>:8996/`.

```bash
.venv/bin/python contrib/walkthrough/run.py new --name melodic        # prints the run folder
.venv/bin/python contrib/walkthrough/run.py leg <run> 1               # leg 1 from nothing
.venv/bin/python contrib/walkthrough/run.py leg <run> 2 --from <run>/checkpoints/01-drums
```

Runs are kept in `~/Music/zpkt/walkthrough/runs` (`WT_RUNS`). The model is `WT_MODEL` (default Claude Sonnet 5.5).
Runs share the one Live, so one at a time. The persona never touches the HW002 sets.
