# Relevance criteria

This file is the single source of truth for what Offshoot extracts and how it
decides. If anything else in the repo disagrees with it, this file wins. The
extraction subagent receives this file verbatim as its rubric, so editing it
changes the pipeline's behaviour on the next run with no code change. The one
exception is adding or renaming an enum level, which must also be changed in
`src/lit_orchestrator/subagents/extraction/schema.py` (a test checks the two agree).

**Calibration status: provisional.** The enum anchors below were written from
five sample extractions and the stated constraints, not from a hand-labelled
set. Run `python calibrate.py` (see the README) to check them against your own
labels and adjust the anchors here.

## Who the project is for

- One undergraduate working alone and part-time. A project should be a few
  weeks of part-time work, not a semester.
- Comfortable with Python and standard machine-learning tooling.
- Compute is a laptop, a free Google Colab session, or calls to a hosted LLM
  API. There is no budget for paid or multi-day GPU time.
- No wet lab, no clinical or proprietary data access.
- Topic is not scored. The arXiv query already restricts the feed to q-bio
  papers cross-listed with cs.LG or cs.AI.
- Unfamiliar background is not a blocker. Prerequisites get absorbed through
  overviews, so `learning_delta` is recorded for information and never gates.

## What counts as a project

A project is a small extension of the paper built on what the authors
released: it reruns or reuses their artifacts to test something they named as
a limitation, a future-work item, or an untested generalisation. The
`deliverable` is an artifact that exists at the end (a harness, a comparison
table, a small benchmark), not a finding. "Show that X improves Y" is a
finding. "A script and results table comparing X and Y on dataset Z" is a
deliverable.

Draft the best candidate project the paper supports even when the paper will
be rejected. The gates then judge that project.

## Fields, in order

The order is deliberate: evidence is written before the judgment it supports.

| Field | Content |
|---|---|
| `objective` | What the paper set out to test or build. |
| `findings` | Key results. Each item has `text` and `section`. |
| `limitations` | Limitations the authors state, quoted verbatim, with `section`. |
| `future_work` | Future-work remarks, quoted verbatim, with `section`. |
| `fixed_date_note` | A concrete external date (deadline, workshop), or null. |
| `candidate_project` | `deliverable` plus exactly three `steps`. The steps are the phase breakdown. |
| `artifacts` | `code_url` (or null), `data_public`, `checkpoints`. Only what the paper says is available now. |
| `compute_evidence` | What the paper says about hardware, model size, and training time, with `section`. |
| `tractability_evidence` | What the paper says about code, data, and availability, with `section`. |
| `learning_delta` | `unfamiliar_items` and a `level`. |
| `disqualifier` | A blocking reason, or null. |
| `compute_gate` | One level from the list below. |
| `tractability` | One level from the list below. |
| `verdict` | `pass` or `reject`. |

Every quoted field carries the section it came from. Use the paper's own
section number or heading. If the paper says nothing on a point, say so in
`text` and use `"whole paper"` as the section; never invent evidence.

Empty lists are correct when the paper has no stated limitations or
future-work remarks. Do not write them on the authors' behalf.

## Gate 1: `disqualifier`

Look for a blocker before judging anything else. Write `null` only if none of
these applies. Otherwise write the label, a colon, and one or two sentences.

- `no_empirical_substrate`: the paper has no experiments, code, or data to
  build on (pure theory, position paper, survey).
- `artifacts_unreleased`: code or data is promised but not available now
  ("upon acceptance", "after peer review", "on request").
- `no_implementation`: no code is released and the method is too involved to
  reimplement faithfully as a small project.
- `restricted_data`: the work depends on private, clinical, or licensed data.
- `needs_wet_lab`: the natural next step requires experiments at a bench.
- `not_grounded`: no project can be tied to a limitation, future-work
  remark, or untested generalisation that the paper itself states.

## Gate 2: `compute_gate`

Judge the candidate project, not the paper's full training run. A project
that only runs inference with a released checkpoint can fit where the
original training did not. Base the level on `compute_evidence`.

| Level | Anchor | Passes |
|---|---|---|
| `fits_laptop` | Runs on CPU or a laptop GPU in hours. Small models, tabular or small-signal data, classical ML. | yes |
| `fits_free_colab` | Fits one free-tier GPU session (T4-class, about 15 GB, under 12 hours). Example: the paper trained on a single T4, or the project is inference or light fine-tuning of a small released model. | yes |
| `fits_llm_api` | The work is calling a hosted LLM (evaluation, benchmarking, prompting). Nothing is trained locally. | yes |
| `exceeds_budget` | Needs more than the above. Example: the paper reports an A100 or H100, multiple GPUs, or multi-day training, and gives no evidence a smaller setup works. | no |
| `no_evidence` | The paper gives no basis for estimating compute. | no |

When the paper reports datacentre hardware and the project would repeat that
workload, choose `exceeds_budget` even if a smaller setup seems plausible.
Plausible is not evidence.

## Gate 3: `tractability`

| Level | Anchor | Passes |
|---|---|---|
| `deliverable_named` | The deliverable is concrete, every step names the specific released artifact or public dataset it uses, and nothing in the steps has to be invented first. | yes |
| `plausible_but_vague` | A project exists in outline, but a step depends on something unspecified ("find a suitable dataset", "adapt the method"). | no |
| `requires_unavailable_resources` | A step needs something that is not available: unreleased code or data, restricted access, or a from-scratch reimplementation. | no |

## `learning_delta.level` (recorded, never gates)

- `minimal`: the methods are standard; nothing new to learn beyond the paper.
- `bounded`: a handful of specific new methods, metrics, or data formats.
- `steep`: a new formalism or subfield has to be learned before starting.

## Verdict

`pass` requires all three: `disqualifier` is null, `compute_gate` is a
passing level, and `tractability` is `deliverable_named`. Anything else is
`reject`. The verdict is checked mechanically against the gates, so decide
the gates from the evidence and let the verdict follow.

## Precision over recall

Reject hard. The feed produces far more papers than one person can act on,
so a missed good paper costs nothing and a wrong `pass` costs a document
that has to be read and discarded. Expect roughly one pass in a hundred.
When a gate is a close call, choose the failing level.

## Known limits

- Papers sometimes link a repository that is empty or does not run. The
  pipeline takes the paper's word. Expect some passes to fail on first
  contact; the weekly read-through catches them.
- Quoted evidence is not checked against the paper text automatically. The
  `section` on each quote is there so it can be checked by hand.
