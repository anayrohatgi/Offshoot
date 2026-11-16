# Dispatch render spec

The document is a pure function of the extraction record. No model call
happens at dispatch. Every line maps to a field; nothing is generated,
summarised, or reworded at render time. If a section cannot be filled from
the record, the schema is wrong: fix the schema, not the renderer.

Implementation: `src/lit_orchestrator/dispatch/render.py`. `render()` needs
no network and no credentials; `gdocs.create_doc()` is the separate step that
uploads the text. Field definitions live in `relevance-criteria.md`.

Only `pass` records are dispatched. Rejects stay in `state.db` and are read
with `review.py`.

## Filename

    YYYY-MM-DD_arxivID_short-title

The date is the dispatch date, not the paper's. `short-title` is the title
lowercased, hyphenated, and cut to 40 characters.

## Layout

```
{filename}

Source     {source_url} · {first author} et al. · {categories} · {pages}pp · {published}
Verdict    PASS  ·  compute: {compute_gate}  ·  tractability: {tractability}

DELIVERABLE
{candidate_project.deliverable}

STEPS
1. {steps[0]}
2. {steps[1]}
3. {steps[2]}

GROUNDED IN
Objective
  {objective}
Findings
  - {text}  [{section}]
Stated limitations
  - {text}  [{section}]
Future work
  - {text}  [{section}]

FEASIBILITY EVIDENCE
Artifacts      code: {code_url} · data public: yes/no · checkpoints: yes/no
Compute        {compute_evidence.text}  [{section}]
Tractability   {tractability_evidence.text}  [{section}]

LEARNING DELTA
Unfamiliar     {unfamiliar_items}
Level          {level}

NOTES
{fixed_date_note.text}  [{section}]
```

## Rules

- The header carries the verdict and both gates, so a folder can be scanned
  by its first lines without opening every document.
- Every quoted field renders its `[section]`. That is what makes a claim
  checkable against the paper during the read-through.
- A verdict is never shown without the evidence lines that produced it.
- Verbatim stays verbatim. Limitations and future work are not trimmed or
  joined.
- Empty sections are omitted, not rendered as "N/A". This covers an empty
  findings, limitations, or future-work list, a null `fixed_date_note`, and a
  missing page count.
- `disqualifier` does not appear in a dispatched document, because rejects
  are never dispatched. `review.py --id` shows it on a `Blocked` line.
- A fixed date found in a paper is a note in the document. It is not sent to
  a calendar or task list; that decision belongs to the weekly read-through.
