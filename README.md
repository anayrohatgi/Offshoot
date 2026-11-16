# Offshoot

Keeping up with bio×AI research means reading across two fields that both
move too fast to track by hand, and the good project ideas are rarely in a
paper's abstract. They sit in a "further studies are needed to..." near the
end of a Discussion section, or in a limitation the authors name and move
past.

Offshoot watches new arXiv papers at that intersection, reads each one in
full, and drafts the small project it supports: something that reuses what
the authors released to test what they said was untested. It then judges
each draft against a strict rubric and sends the few that survive to Google
Docs as one document per project. Every project is an offshoot of a question
someone else asked and did not have time to answer.

## What it produces

A dispatched draft looks like this (shortened):

```
2026-11-16_2609.19453_sharpness-aware-minimization-sam-improve

Source     https://arxiv.org/abs/2609.19453 · Kaitlin Zareno et al. · cs.LG, q-bio.QM, stat.ML · 2026-09-16
Verdict    PASS  ·  compute: fits_free_colab  ·  tractability: deliverable_named

DELIVERABLE
A rerun of the paper's Adam-vs-SAM comparison on a second, architecturally
different Raman classification setup, with a results table testing the
limitation the authors named: whether SAM's gain generalizes across datasets
and architectures.

STEPS
1. Pull a second public bacterial Raman spectral dataset and define a shallow 1D-CNN...
2. Reuse their public SAM implementation to train both Adam and SAM baselines...
3. Report whether SAM's accuracy gain and variance reduction replicate...

FEASIBILITY EVIDENCE
Artifacts      code: https://github.com/Tadesse-Lab/SAM-Raman-Diagnostics · data public: yes · checkpoints: no
Compute        We trained all models on a single host having 1 NVIDIA T4 GPU.  [3.2]
```

Each claim carries the section of the paper it came from, so it can be
checked. The full record is in `fixtures/example_draft.json`, and
`fixtures/example_reject.json` shows a near miss: a well-matched paper
rejected because its code and data were not yet released.

Most papers are rejected, by design. The feed has far more papers than one
person can act on, so a missed good paper costs nothing and a wrong accept
costs a document that has to be read and thrown away.

## How it works

1. **Ingest.** Fetch metadata for papers from the last five days that are in
   a `q-bio.*` category and also in `cs.LG` or `cs.AI`.
2. **Extract and score.** For each new paper, a subagent reads the full text,
   fills a structured record (objective, findings, stated limitations,
   future work, a candidate project, evidence about compute and artifacts),
   and applies three gates: a disqualifier check, a compute gate, and a
   tractability gate. All three must clear for a `pass`.
3. **Dispatch.** Each `pass` is rendered to text and created as a Google Doc.
   This step is deterministic and makes no model call.

It is built on the Claude Agent SDK as a coordinator with subagents. The
coordinator delegates each stage, runs extractions in parallel, and passes
each subagent only what it needs. Every paper, accepted or rejected, is
stored in a local SQLite file so nothing is processed twice and rejections
can be reviewed. See [docs/architecture.md](docs/architecture.md) for the
design and [docs/relevance-criteria.md](docs/relevance-criteria.md) for the
rubric.

## Setup

Requires Python 3.11 or later.

```
git clone https://github.com/anayrohatgi/Offshoot
cd Offshoot
pip install -e ".[dev]"
cp .env.example .env
pytest
```

### Claude credentials

Set one of these in `.env`:

- `ANTHROPIC_API_KEY`, a pay-as-you-go key from the Claude Console.
- `CLAUDE_CODE_OAUTH_TOKEN`, from running `claude setup-token`, which bills
  a Claude subscription instead. Do not set both; the API key takes precedence.

### Google Docs

1. In Google Cloud Console, create a project and enable the **Google Drive API**.
2. Configure the OAuth consent screen and set its publishing status to
   **In production**. In "Testing" status Google expires refresh tokens after
   seven days, and dispatch would stop working a week later.
3. Create an OAuth client of type **Desktop app**. Put its id and secret in
   `.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
4. Run `python scripts/google_auth.py`. It asks for consent in a browser,
   creates a Drive folder named "Offshoot drafts", and prints
   `GOOGLE_REFRESH_TOKEN` and `GOOGLE_DRIVE_FOLDER_ID` for `.env`.

The only scope requested is `drive.file`, which reaches files this app
created and nothing else in the Drive. For that reason the folder has to be
the one the script creates.

Google setup is optional for a first run. Without it, accepted drafts are
stored and queued, and are sent once credentials exist.

## Running

```
offshoot --max-papers 5 --dry-run    # first run: five papers, no Docs created
offshoot                             # normal run
```

`--max-papers` caps extractions per run (default 25), which is where the
cost is. `--lookback-days` changes the window (default 5). `--verbose` prints
every agent message, tool call, and task event, which is the first thing to
turn on when a run misbehaves.

### On a schedule

`.github/workflows/daily.yml` runs the pipeline daily on GitHub Actions. Add
these repository secrets under Settings → Secrets and variables → Actions:
one Claude credential (`ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`) and
the four `GOOGLE_*` values. The state file is carried between runs in the
Actions cache. A failed run shows as failed and sends GitHub's usual email.

GitHub disables scheduled workflows in a public repository after 60 days
without repository activity, and sends a notice first.

## Reviewing

```
python review.py                  # recent rejects and why each was blocked
python review.py --passes         # accepted drafts with their Doc links
python review.py --id 2609.19453  # one full draft
python review.py --runs           # run history
```

## Tuning the rubric

The gate definitions in `docs/relevance-criteria.md` are given to the model
verbatim, so editing that file changes behaviour on the next run. To check
the rubric against your own judgment:

```
python calibrate.py export -n 35   # writes drafts to read and a label file to fill in
python calibrate.py compare        # shows where you and the model disagree
```

The export hides the model's verdicts so they do not anchor your labels.

## Limits

- arXiv only.
- A paper with neither LaTeX source nor an HTML rendering is skipped. It is
  not scored from its abstract.
- The pipeline believes what a paper says about its code and data. A linked
  repository that is empty or broken is found only when someone opens it.
- Quotations are not verified against the paper text automatically.
- Papers are judged one at a time. Finding connections across drafts is left
  to reading the folder.

## Layout

```
src/lit_orchestrator/
  coordinator/coordinator.py     orchestration, persistence, dispatch
  subagents/ingest/              arXiv client, tool, agent definition
  subagents/extraction/          paper text, schema, tools, agent definition
  dispatch/                      render to text, upload to Google Docs
  state/db.py                    SQLite state
  run_context.py                 result channel from tools to coordinator
docs/                            rubric, render spec, architecture
fixtures/                        one accepted and one rejected example record
review.py  calibrate.py          read-only review and calibration tools
scripts/google_auth.py           one-time Google setup
```
