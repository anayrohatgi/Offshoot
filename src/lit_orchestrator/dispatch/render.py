"""Render an extraction record as the text of a project-draft document.

A pure function of the record: no LLM call, no network, no credentials.
Nothing is summarised or reworded here. If a section cannot be filled from
the record, the schema is wrong; fix the schema, not the renderer.
Spec: docs/dispatch-doc-template.md.
"""

from __future__ import annotations

import re
from datetime import date


def filename(record: dict, dispatch_date: date) -> str:
    """YYYY-MM-DD_arxivID_short-title, where the date is the dispatch date."""
    slug = re.sub(r"[^a-z0-9]+", "-", record["paper"]["title"].lower()).strip("-")
    slug = slug[:40].rstrip("-")
    return f"{dispatch_date.isoformat()}_{record['paper']['arxiv_id']}_{slug}"


def _quote(item: dict) -> str:
    return f"{item['text']}  [{item['section']}]"


def _section(title: str, lines: list[str]) -> list[str]:
    """Empty sections are omitted entirely, never rendered as N/A."""
    return ["", title, *lines] if lines else []


def _bullets(label: str, items: list[dict]) -> list[str]:
    return [label, *(f"  - {_quote(item)}" for item in items)] if items else []


def render(record: dict, dispatch_date: date, include_disqualifier: bool = False) -> str:
    paper = record["paper"]
    authors = paper.get("authors") or []
    byline = f"{authors[0]} et al." if len(authors) > 1 else (authors[0] if authors else None)
    source = [paper["source_url"], byline, ", ".join(paper.get("categories") or []),
              f"{paper['pages']}pp" if paper.get("pages") else None, paper.get("published")]
    artifacts = record["artifacts"]
    project = record["candidate_project"]
    delta = record["learning_delta"]

    lines = [
        filename(record, dispatch_date),
        "",
        "Source     " + " · ".join(part for part in source if part),
        # The header carries the gates so a folder can be scanned without opening anything.
        f"Verdict    {record['verdict'].upper()}  ·  compute: {record['compute_gate']}"
        f"  ·  tractability: {record['tractability']}",
    ]
    if include_disqualifier and record.get("disqualifier"):
        lines.append(f"Blocked    {record['disqualifier']}")

    lines += _section("DELIVERABLE", [project["deliverable"]])
    lines += _section("STEPS", [f"{i}. {step}" for i, step in enumerate(project["steps"], 1)])
    lines += _section("GROUNDED IN", [
        "Objective", f"  {record['objective']}",
        *_bullets("Findings", record["findings"]),
        *_bullets("Stated limitations", record["limitations"]),
        *_bullets("Future work", record["future_work"]),
    ])
    lines += _section("FEASIBILITY EVIDENCE", [
        f"Artifacts      code: {artifacts['code_url'] or 'none'}"
        f" · data public: {'yes' if artifacts['data_public'] else 'no'}"
        f" · checkpoints: {'yes' if artifacts['checkpoints'] else 'no'}",
        f"Compute        {_quote(record['compute_evidence'])}",
        f"Tractability   {_quote(record['tractability_evidence'])}",
    ])
    lines += _section("LEARNING DELTA", [
        *([f"Unfamiliar     {'; '.join(delta['unfamiliar_items'])}"] if delta["unfamiliar_items"] else []),
        f"Level          {delta['level']}",
    ])
    if record.get("fixed_date_note"):
        lines += _section("NOTES", [_quote(record["fixed_date_note"])])
    return "\n".join(lines) + "\n"
