import copy
import json

import pytest

from lit_orchestrator import config
from lit_orchestrator.subagents.extraction import schema


def fields(name):
    record = json.loads((config.FIXTURES_DIR / name).read_text())
    return {"arxiv_id": record["paper"]["arxiv_id"], **{k: v for k, v in record.items() if k != "paper"}}


@pytest.mark.parametrize("name", ["example_draft.json", "example_reject.json"])
def test_fixtures_are_valid(name):
    f = fields(name)
    assert schema.validate_extraction(f, expected_arxiv_id=f["arxiv_id"]) == []


def test_evidence_comes_before_judgments():
    order = list(schema.EXTRACTION_SCHEMA["properties"])
    assert order.index("compute_evidence") < order.index("disqualifier") < order.index("compute_gate")
    assert order[-1] == "verdict"


def test_pass_with_failing_gate_is_rejected():
    f = fields("example_draft.json")
    f["compute_gate"] = "exceeds_budget"
    problems = schema.validate_extraction(f)
    assert len(problems) == 1 and "must be 'reject'" in problems[0]


def test_pass_with_disqualifier_is_rejected():
    f = fields("example_draft.json")
    f["disqualifier"] = "restricted_data: needs hospital records"
    assert schema.validate_extraction(f)


def test_structural_errors_name_the_field():
    f = copy.deepcopy(fields("example_draft.json"))
    f["candidate_project"]["steps"] = ["only", "two"]
    del f["findings"][0]["section"]
    f["tractability"] = "easy"
    problems = "\n".join(schema.validate_extraction(f))
    assert "candidate_project/steps" in problems
    assert "findings/0" in problems
    assert "tractability" in problems


def test_wrong_arxiv_id():
    assert schema.validate_extraction(fields("example_draft.json"), expected_arxiv_id="0000.00000")


def test_every_enum_level_is_documented_in_the_rubric():
    rubric = config.RUBRIC_PATH.read_text()
    for level in schema.COMPUTE_GATE + schema.TRACTABILITY + schema.LEARNING_LEVEL:
        assert f"`{level}`" in rubric, f"{level} is in schema.py but not in relevance-criteria.md"
