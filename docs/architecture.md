# How Offshoot works

A walkthrough of the orchestration, written to be read next to the code.

## The shape

```
                 ┌──────────────────────── Python driver ────────────────────────┐
                 │ coordinator.py: sequencing, dedup, persistence, dispatch      │
                 └───────┬──────────────────────────────────────────────┬────────┘
                directive│                                   reads after│return
                         ▼                                              │
              ┌─────────────────────┐                          ┌────────┴───────┐
              │  coordinator agent  │                          │   RunContext   │
              │ (delegates by Task) │                          └────────▲───────┘
              └───┬─────────────┬───┘                                   │ tool handlers
             Task │             │ Task × N, in parallel                 │ write results
                  ▼             ▼                                       │
          ┌────────────┐  ┌───────────────────┐  fetch_arxiv_candidates │
          │   ingest   │  │    extraction     │  fetch_paper_text       │
          │  subagent  │  │ subagent, 1/paper │  submit_extraction ─────┘
          └────────────┘  └───────────────────┘
```

One run does three things in order: ingest, extraction with scoring, and
dispatch. The first two are delegated to subagents. Dispatch is plain Python.

## Who does what

**The Python driver** (`coordinator/coordinator.py`) owns everything that
must be deterministic: the order of stages, which papers are new, what gets
written to `state.db`, and dispatch. It is the only code that touches state.

**The coordinator agent** is a Claude session whose only built-in tool is
`Task`. The driver hands it one directive at a time ("delegate ingest with
these values", "delegate these five papers"). It writes the Task prompts and
issues the calls. It never does the work itself.

**The subagents** are defined in `subagents/*/agent.py`. Each has its own
system prompt and a `tools` list limited to its stage. A subagent starts
every invocation with an empty context: it sees its system prompt and the
Task prompt, and nothing else.

## Three rules the design follows

**1. Context is passed explicitly.** Because subagents share no memory, the
Task prompt must contain everything the subagent needs. The coordinator's
system prompt says this, and each directive lists the exact values to pass.
The extraction subagent's standing knowledge (the rubric and two worked
examples) is in its system prompt, built from `docs/relevance-criteria.md`
at run time.

**2. Handles, not payloads.** The coordinator passes an `arxiv_id` and
title. The extraction subagent calls `fetch_paper_text` to get the text
itself. A full paper never enters the coordinator's context, which would
otherwise grow by tens of thousands of tokens per paper.

**3. Results come back through tools.** A subagent finishes by calling a
tool (`fetch_arxiv_candidates` or `submit_extraction`). The handlers are
ordinary Python functions in this process (an in-process MCP server), and
they write the result into `RunContext`. The driver reads `RunContext` once
the Task call has returned. The alternative, parsing JSON out of a
subagent's final chat message, breaks whenever the model adds a sentence or
a code fence.

## Structured output and the retry loop

`submit_extraction`'s input schema is the extraction schema
(`subagents/extraction/schema.py`). The model's answer is therefore a tool
call shaped by that schema, not free text that hopefully contains JSON.

Field order in the schema is deliberate. The model fills fields top to
bottom, so each one is conditioned on those before it. Evidence fields come
before the judgments that depend on them, and `disqualifier` comes before
the gate levels, so the verdict is derived from quoted evidence.

The handler validates each submission in two passes:

1. Structure, with `jsonschema`: required fields, exactly three steps, enum
   membership, a `section` on every quote.
2. Meaning: the `arxiv_id` matches a paper in this run, and `verdict` equals
   what the three gates imply.

A failed submission is returned as a tool error that names each problem.
The subagent fixes them and submits again, up to three attempts. After that
the paper is recorded as failed and retried on a later run.

Paper metadata (title, authors, categories) is never typed by the model.
The handler joins the model's fields to the metadata that ingest fetched.

## Parallelism

Extraction runs in batches of five. For each batch the coordinator agent
issues five Task calls in one message, so five subagents run at once.
`fetch_paper_text` holds a lock and waits three seconds between arXiv
requests, so parallel subagents still respect one shared rate limit. The
driver persists after each batch, so a crash loses at most one batch.

## State, dedup, and self-healing

`state.db` has one row per paper holding the full record, pass or reject,
and one row per run.

Polling uses a fixed five-day lookback window with dedup by `arxiv_id`,
not a "since last run" cursor. A missed or failed run needs no recovery:
the papers it skipped are still inside the next run's window. The repeated
cost is metadata only, because dedup happens before any extraction.

Two more cases heal the same way. A failed extraction is retried on the
next run, twice at most. An accepted draft whose Google upload failed stays
queued and is sent by the next run.

## Dispatch

Dispatch has no model call. `dispatch/render.py` turns a record into text,
and `dispatch/gdocs.py` uploads it to Drive, which converts it to a Google
Doc. Only passes are dispatched. Nothing is created in a task list or
calendar: deciding to commit to a project is a human step.

## Failure modes worth knowing

| What goes wrong | What happens |
|---|---|
| arXiv is down during ingest | The ingest tool returns an error, the run exits non-zero, and the next run covers the gap. |
| A paper has no LaTeX source or HTML | Recorded as failed. It is never scored from the abstract alone. |
| The model submits an inconsistent verdict | Rejected by the validator; the subagent resubmits. |
| A subagent ends without submitting | The driver finds nothing in `RunContext` for that id and records a failure. |
| A Task call runs its subagent in the background, so the coordinator's turn ends first | `delegate()` keeps waiting until every started task has finished or the expected results have arrived. |
| Google upload fails | The draft stays queued; the run exits non-zero so the failure is visible. |
| The Actions cache holding `state.db` is evicted | Papers in the current window are extracted again and passes are dispatched again. Caches expire after seven days without use, so this needs a week of no runs. |
| The coordinator agent calls a stage tool itself instead of delegating | Possible: the stage tools are approved for the whole session so that subagents can use them. Its system prompt forbids it, and a result submitted that way would still pass the same validation. It has no other built-in tools. |
