"""Drives the tool handlers the way a subagent would, without calling a model."""
import asyncio
import json

import pytest

from lit_orchestrator import config
from lit_orchestrator.coordinator import coordinator
from lit_orchestrator.run_context import RunContext
from lit_orchestrator.state import db
from lit_orchestrator.subagents.extraction import tools as extraction_tools


def record(name):
    return json.loads((config.FIXTURES_DIR / name).read_text())


def as_fields(rec):
    return {"arxiv_id": rec["paper"]["arxiv_id"], **{k: v for k, v in rec.items() if k != "paper"}}


@pytest.fixture
def ctx():
    return RunContext(candidates=[record("example_draft.json")["paper"], record("example_reject.json")["paper"]])


@pytest.fixture
def submit(ctx, tmp_path):
    handler = extraction_tools.build_extraction_tools(ctx, tmp_path)[1].handler
    return lambda args: asyncio.run(handler(args))


def test_valid_submission_lands_in_context_with_trusted_metadata(ctx, submit):
    rec = record("example_draft.json")
    result = submit(as_fields(rec))
    assert not result.get("is_error")
    assert ctx.extractions["2609.19453"] == rec
    assert list(ctx.extractions["2609.19453"])[0] == "paper"


def test_validation_retry_loop(ctx, submit):
    bad = as_fields(record("example_draft.json"))
    bad["verdict"] = "reject"                       # contradicts the gates
    first = submit(bad)
    assert first["is_error"] and "must be 'pass'" in first["content"][0]["text"]
    assert "2609.19453" not in ctx.extractions
    assert not submit(as_fields(record("example_draft.json"))).get("is_error")  # corrected resubmission
    assert "2609.19453" in ctx.extractions and "2609.19453" not in ctx.last_errors


def test_attempt_limit(ctx, submit):
    bad = as_fields(record("example_draft.json"))
    bad["tractability"] = "easy"
    for _ in range(extraction_tools.MAX_SUBMIT_ATTEMPTS):
        assert submit(bad)["is_error"]
    assert submit(as_fields(record("example_draft.json")))["is_error"]  # too late even if valid
    assert "2609.19453" not in ctx.extractions


def test_unknown_paper_is_refused(ctx, submit):
    fields = as_fields(record("example_draft.json"))
    fields["arxiv_id"] = "9999.99999"
    assert submit(fields)["is_error"]


def test_fetch_paper_text_pages_and_reports_missing(ctx, tmp_path, monkeypatch):
    fetch = extraction_tools.build_extraction_tools(ctx, tmp_path)[0].handler
    (tmp_path / "2609.19453.latex.txt").write_text("a" * 50_000 + "b" * 10)
    first = asyncio.run(fetch({"arxiv_id": "2609.19453"}))["content"][0]["text"]
    assert "part 1 of 2" in first and first.endswith("a")
    assert asyncio.run(fetch({"arxiv_id": "2609.19453", "part": 2}))["content"][0]["text"].endswith("b" * 10)
    assert asyncio.run(fetch({"arxiv_id": "2609.19453", "part": 3}))["is_error"]

    def unavailable(arxiv_id, cache_dir):
        raise extraction_tools.PaperTextUnavailable("no text")
    monkeypatch.setattr(extraction_tools, "get_paper_text", unavailable)
    assert asyncio.run(fetch({"arxiv_id": "2609.19180"}))["is_error"]
    assert ctx.last_errors["2609.19180"] == "no text"


def test_persist_dedup_retry_and_dispatch(ctx, tmp_path, monkeypatch, capsys):
    conn = db.connect(tmp_path / "state.db")
    passing, rejecting = record("example_draft.json"), record("example_reject.json")
    ctx.extractions[passing["paper"]["arxiv_id"]] = passing        # one succeeded, one never submitted
    batch = ctx.candidates

    assert coordinator.persist_batch(conn, ctx, batch) == (1, 0, 1)
    # the pass is done for good; the failure is retried once more, then given up on
    assert [p["arxiv_id"] for p in coordinator.select_new(conn, batch, 10)] == ["2609.19180"]
    db.save_failure(conn, rejecting["paper"], "again")
    assert coordinator.select_new(conn, batch, 10) == []

    # no credentials: the pass stays queued and nothing is sent
    monkeypatch.setattr(config, "google_credentials", lambda: None)
    assert coordinator.dispatch_pending(conn, dry_run=False) == (0, 0)
    assert len(db.pending_dispatch(conn)) == 1

    creds = {k: "x" for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
                              "GOOGLE_REFRESH_TOKEN", "GOOGLE_DRIVE_FOLDER_ID")}
    monkeypatch.setattr(config, "google_credentials", lambda: creds)
    monkeypatch.setattr(coordinator.gdocs, "get_access_token", lambda *a: "token")
    sent = []
    monkeypatch.setattr(coordinator.gdocs, "create_doc",
                        lambda token, name, text, folder: sent.append(name) or ("doc1", "https://docs/doc1"))
    assert coordinator.dispatch_pending(conn, dry_run=False) == (1, 0)
    assert sent[0].endswith("_2609.19453_sharpness-aware-minimization-sam-improve")
    assert coordinator.dispatch_pending(conn, dry_run=False) == (0, 0)   # never sent twice
    assert sent == sent[:1]


def test_select_new_is_oldest_first_and_capped(tmp_path):
    conn = db.connect(tmp_path / "state.db")
    newest_first = [{"arxiv_id": str(i), "title": "t"} for i in (3, 2, 1)]
    assert [p["arxiv_id"] for p in coordinator.select_new(conn, newest_first, 2)] == ["1", "2"]


def test_extraction_agent_prompt_carries_rubric_and_examples():
    from lit_orchestrator.subagents.extraction.agent import build_extraction_agent
    agent = build_extraction_agent()
    assert "Gate 2: `compute_gate`" in agent.prompt and "SAM-Raman-Diagnostics" in agent.prompt
    assert agent.tools == ["mcp__offshoot__fetch_paper_text", "mcp__offshoot__submit_extraction"]
