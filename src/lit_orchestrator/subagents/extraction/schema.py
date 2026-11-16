"""The extraction/scoring schema and its validator.

docs/relevance-criteria.md is the authoritative description of every field
and enum level. This file is the machine-readable form of the same thing;
tests/test_schema.py fails if an enum value here is missing from that doc.

FIELD ORDER IS LOAD-BEARING. The model fills the tool input top to bottom,
so each field is conditioned on the ones above it. Evidence comes before the
judgments it supports, and `disqualifier` comes before the gate enums, so a
verdict is derived from quoted evidence instead of being justified after the
fact. Do not reorder for tidiness.
"""

from __future__ import annotations

import jsonschema

COMPUTE_GATE_PASSING = ["fits_laptop", "fits_free_colab", "fits_llm_api"]
COMPUTE_GATE = COMPUTE_GATE_PASSING + ["exceeds_budget", "no_evidence"]
TRACTABILITY_PASSING = "deliverable_named"
TRACTABILITY = [TRACTABILITY_PASSING, "plausible_but_vague", "requires_unavailable_resources"]
LEARNING_LEVEL = ["minimal", "bounded", "steep"]  # recorded, never gates
VERDICT = ["pass", "reject"]

_QUOTE = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "minLength": 1},
        "section": {"type": "string", "minLength": 1,
                    "description": "Section of the paper the text comes from, e.g. '3.2' or '5 Discussion'."},
    },
    "required": ["text", "section"],
    "additionalProperties": False,
}
_QUOTES = {"type": "array", "items": _QUOTE}

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "arxiv_id": {"type": "string"},
        "objective": {"type": "string", "minLength": 1,
                      "description": "What the paper set out to test or build, in one or two sentences."},
        "findings": {**_QUOTES, "description": "Key results, each with its section."},
        "limitations": {**_QUOTES, "description": "Limitations the authors state, quoted verbatim."},
        "future_work": {**_QUOTES, "description": "Future-work remarks, quoted verbatim."},
        "fixed_date_note": {
            "anyOf": [_QUOTE, {"type": "null"}],
            "description": "A concrete external date in the paper (deadline, workshop). Null if none.",
        },
        "candidate_project": {
            "type": "object",
            "properties": {
                "deliverable": {"type": "string", "minLength": 1,
                                "description": "An artifact that would exist at the end, not a finding."},
                "steps": {"type": "array", "items": {"type": "string", "minLength": 1},
                          "minItems": 3, "maxItems": 3,
                          "description": "Exactly three phases, in order."},
            },
            "required": ["deliverable", "steps"],
            "additionalProperties": False,
        },
        "artifacts": {
            "type": "object",
            "properties": {
                "code_url": {"type": ["string", "null"]},
                "data_public": {"type": "boolean"},
                "checkpoints": {"type": "boolean"},
            },
            "required": ["code_url", "data_public", "checkpoints"],
            "additionalProperties": False,
        },
        "compute_evidence": _QUOTE,
        "tractability_evidence": _QUOTE,
        "learning_delta": {
            "type": "object",
            "properties": {
                "unfamiliar_items": {"type": "array", "items": {"type": "string"}},
                "level": {"type": "string", "enum": LEARNING_LEVEL},
            },
            "required": ["unfamiliar_items", "level"],
            "additionalProperties": False,
        },
        "disqualifier": {"type": ["string", "null"],
                         "description": "The blocking reason, or null if nothing blocks the project."},
        "compute_gate": {"type": "string", "enum": COMPUTE_GATE},
        "tractability": {"type": "string", "enum": TRACTABILITY},
        "verdict": {"type": "string", "enum": VERDICT},
    },
    "additionalProperties": False,
}
EXTRACTION_SCHEMA["required"] = list(EXTRACTION_SCHEMA["properties"])

_validator = jsonschema.Draft202012Validator(EXTRACTION_SCHEMA)


def expected_verdict(fields: dict) -> str:
    """The verdict is a pure function of the three gates. All three must clear."""
    clears = (
        fields["disqualifier"] is None
        and fields["compute_gate"] in COMPUTE_GATE_PASSING
        and fields["tractability"] == TRACTABILITY_PASSING
    )
    return "pass" if clears else "reject"


def validate_extraction(fields: dict, expected_arxiv_id: str | None = None) -> list[str]:
    """Return human-readable problems; an empty list means the submission is valid.

    The messages go back to the model as the tool error, so they say what to fix.
    """
    problems = [
        f"{'/'.join(str(p) for p in error.absolute_path) or '(root)'}: {error.message}"
        for error in sorted(_validator.iter_errors(fields), key=lambda e: list(e.absolute_path))
    ]
    if problems:
        return problems  # semantic checks below assume a structurally valid record

    if expected_arxiv_id is not None and fields["arxiv_id"] != expected_arxiv_id:
        problems.append(f"arxiv_id: expected {expected_arxiv_id!r}, got {fields['arxiv_id']!r}")
    expected = expected_verdict(fields)
    if fields["verdict"] != expected:
        problems.append(
            f"verdict: {fields['verdict']!r} contradicts the gates. With disqualifier="
            f"{'null' if fields['disqualifier'] is None else 'set'}, compute_gate="
            f"{fields['compute_gate']!r}, tractability={fields['tractability']!r} the verdict "
            f"must be {expected!r}. Re-check the gates against your evidence first; change "
            "the verdict only if the gates are right."
        )
    return problems


def build_record(paper: dict, fields: dict) -> dict:
    """Join trusted ingest metadata with the model's fields, preserving field order."""
    record = {"paper": {key: paper.get(key) for key in (
        "arxiv_id", "title", "authors", "source_url", "categories", "pages", "published")}}
    record.update({key: fields[key] for key in EXTRACTION_SCHEMA["properties"] if key != "arxiv_id"})
    return record
