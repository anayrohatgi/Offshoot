"""The Coordinator: the only component that invokes another component.

Two layers work together here.

- A Claude session (the "coordinator agent") whose only tool is Task. It
  receives a directive and delegates to the ingest or extraction subagent.
  Each subagent starts with an empty context, so every Task prompt has to
  carry what that subagent needs.
- This Python driver, which owns everything deterministic: what to delegate
  next, dedup against state.db, persistence, and dispatch.

Subagents never call each other and never touch state. Each one hands its
result back through a tool call that lands in RunContext, and the driver
reads RunContext only after the delegation has returned.

Run with `python -m lit_orchestrator.coordinator.coordinator` or `offshoot`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date

from claude_agent_sdk import (
    TERMINAL_TASK_STATUSES,
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TaskNotificationMessage,
    TaskStartedMessage,
    TaskUpdatedMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
)

from lit_orchestrator import config
from lit_orchestrator.dispatch import gdocs
from lit_orchestrator.dispatch.render import filename, render
from lit_orchestrator.run_context import RunContext
from lit_orchestrator.state import db
from lit_orchestrator.subagents.extraction.agent import (
    EXTRACTION_AGENT_NAME,
    EXTRACTION_TOOLS,
    build_extraction_agent,
)
from lit_orchestrator.subagents.extraction.tools import build_extraction_tools
from lit_orchestrator.subagents.ingest.agent import INGEST_AGENT_NAME, INGEST_TOOL, ingest_agent
from lit_orchestrator.subagents.ingest.tools import build_ingest_tools

COORDINATOR_SYSTEM_PROMPT = f"""\
You are the coordinator of a literature-monitoring pipeline. You do none of
the work yourself. Your only action is to delegate with the Task tool to one
of two subagents:

- "{INGEST_AGENT_NAME}": fetches candidate paper metadata from arXiv.
- "{EXTRACTION_AGENT_NAME}": reads ONE paper and submits a structured record for it.

Rules:
- Subagents share no memory with you or with each other. Every Task prompt
  must be self-contained: put every value the subagent needs into the prompt.
- Pass identifiers, not content. Give the extraction subagent an arxiv_id and
  title; it fetches the paper text itself.
- When a directive covers several papers, issue all the Task calls in a
  single message so they run in parallel.
- Never call any tool other than Task. Never retry a subagent that failed;
  the driver decides about retries.
- After the subagents return, reply with one short status line per Task.
"""


def build_options(ctx: RunContext) -> ClaudeAgentOptions:
    server = create_sdk_mcp_server(
        name=config.SERVER_NAME,
        tools=build_ingest_tools(ctx) + build_extraction_tools(ctx, config.CACHE_DIR),
    )
    return ClaudeAgentOptions(
        system_prompt=COORDINATOR_SYSTEM_PROMPT,
        model=config.COORDINATOR_MODEL,
        agents={
            INGEST_AGENT_NAME: ingest_agent,
            EXTRACTION_AGENT_NAME: build_extraction_agent(),
        },
        mcp_servers={config.SERVER_NAME: server},
        # The coordinator's only built-in tool is Task. The MCP tools are
        # pre-approved so the subagents (whose own `tools` lists restrict them
        # to their stage) can call them in a run with nobody there to approve.
        tools=["Task"],
        allowed_tools=["Task", INGEST_TOOL, *EXTRACTION_TOOLS],
    )


DELEGATION_TIMEOUT_SECONDS = 20 * 60


def _describe(message) -> str | None:
    """One line per message for --verbose, so a failed run shows what the agents did."""
    who = "subagent" if getattr(message, "parent_tool_use_id", None) else "coordinator"
    if isinstance(message, (AssistantMessage, UserMessage)) and isinstance(message.content, list):
        parts = []
        for block in message.content:
            if isinstance(block, TextBlock) and block.text.strip():
                parts.append(f"says: {block.text.strip()[:300]}")
            elif isinstance(block, ToolUseBlock):
                parts.append(f"calls {block.name} {str(block.input)[:200]}")
            elif isinstance(block, ToolResultBlock):
                flag = "ERROR " if block.is_error else ""
                parts.append(f"tool result: {flag}{str(block.content)[:300]}")
        return f"    [{who}] " + " | ".join(parts) if parts else None
    if isinstance(message, TaskStartedMessage):
        return f"    [task {message.task_id}] started: {message.description}"
    if isinstance(message, TaskNotificationMessage):
        return f"    [task {message.task_id}] {message.status}: {message.summary[:200]}"
    if isinstance(message, TaskUpdatedMessage):
        return f"    [task {message.task_id}] update: {message.patch}"
    if isinstance(message, ResultMessage):
        return f"    [turn ended] origin={message.origin} error={message.is_error}"
    return None


async def delegate(client: ClaudeSDKClient, directive: str, done, verbose: bool = False) -> None:
    """Send one directive and return once the subagents it started have finished.

    The end of the coordinator agent's turn is not enough. A Task call can run
    its subagent in the background: the call returns at once, the turn ends,
    and the subagent is still working. So this waits until the turn has ended
    AND either no started task is still running or `done()` reports that every
    expected result has arrived in RunContext. If neither happens in time it
    returns anyway, and the caller records whatever is missing as failed.
    """
    await client.query(directive)
    try:
        async with asyncio.timeout(DELEGATION_TIMEOUT_SECONDS):
            await _wait_for_delegation(client, done, verbose)
    except TimeoutError:
        print(f"  warning: delegation still unfinished after {DELEGATION_TIMEOUT_SECONDS // 60} minutes; moving on")


async def _wait_for_delegation(client: ClaudeSDKClient, done, verbose: bool) -> None:
    running: set[str] = set()
    turn_ended = False
    async for message in client.receive_messages():
        if verbose and (line := _describe(message)):
            print(line)

        if isinstance(message, TaskStartedMessage):
            running.add(message.task_id)
        elif isinstance(message, TaskNotificationMessage):
            running.discard(message.task_id)
        elif isinstance(message, TaskUpdatedMessage):
            if (message.status or message.patch.get("status")) in TERMINAL_TASK_STATUSES:
                running.discard(message.task_id)
        elif isinstance(message, AssistantMessage) and message.parent_tool_use_id is None:
            for block in message.content:
                if isinstance(block, ToolUseBlock) and block.name == "Task" and not verbose:
                    print(f"  delegated -> {block.input.get('subagent_type')}: "
                          f"{block.input.get('description', '')}")
        elif isinstance(message, ResultMessage):
            if message.is_error:
                raise RuntimeError(f"coordinator turn failed: {message.result or message.subtype}")
            # A background task finishing makes the session start a turn of its
            # own. Only a turn that answers our directive counts as its end.
            if message.origin is None or message.origin.get("kind") == "human":
                turn_ended = True
                if message.total_cost_usd is not None:
                    print(f"  cost reported by the SDK so far: ${message.total_cost_usd:.2f}")

        if turn_ended and (not running or done()):
            return


def ingest_directive(lookback_days: int) -> str:
    return (
        f'Delegate one Task to the "{INGEST_AGENT_NAME}" subagent. Its prompt must state '
        f"these values exactly: bio_categories={config.BIO_CATEGORIES}, "
        f"ml_categories={config.ML_CATEGORIES}, lookback_days={lookback_days}, "
        f"max_results={config.MAX_FETCH}."
    )


def extraction_directive(batch: list[dict]) -> str:
    papers = "\n".join(f"- arxiv_id={p['arxiv_id']} | title={p['title']}" for p in batch)
    return (
        f'Delegate {len(batch)} Task call(s) to the "{EXTRACTION_AGENT_NAME}" subagent, one per '
        "paper below, all in a single message. Each Task prompt must contain that "
        f"paper's arxiv_id and title and nothing about any other paper.\n\n{papers}"
    )


def select_new(conn, candidates: list[dict], limit: int) -> list[dict]:
    """Papers not yet handled, oldest first so nothing ages out of the lookback window."""
    fresh = [p for p in reversed(candidates) if not db.is_done(conn, p["arxiv_id"], config.MAX_ATTEMPTS)]
    return fresh[:limit]


def persist_batch(conn, ctx: RunContext, batch: list[dict]) -> tuple[int, int, int]:
    """Write one batch to state.db. Returns (passed, rejected, failed)."""
    passed = rejected = failed = 0
    for paper in batch:
        arxiv_id = paper["arxiv_id"]
        record = ctx.extractions.get(arxiv_id)
        if record is None:
            error = ctx.last_errors.get(arxiv_id, "subagent returned without submitting")
            db.save_failure(conn, paper, error)
            print(f"  FAILED {arxiv_id}: {error}")
            failed += 1
            continue
        db.save_extraction(conn, record)
        print(f"  {record['verdict'].upper():6} {arxiv_id}  {paper['title'][:70]}")
        passed += record["verdict"] == "pass"
        rejected += record["verdict"] == "reject"
    return passed, rejected, failed


def dispatch_pending(conn, dry_run: bool) -> tuple[int, int]:
    """Deterministic: render each accepted record and create its Doc. No LLM call.

    Returns (dispatched, errors). Covers drafts a previous run accepted but
    could not send, so a Google outage delays a Doc instead of losing it.
    """
    pending = db.pending_dispatch(conn)
    if not pending:
        return 0, 0
    creds = config.google_credentials()
    if dry_run or creds is None:
        reason = "dry run" if dry_run else "Google credentials not set"
        print(f"{len(pending)} accepted draft(s) not dispatched ({reason}). "
              "They stay queued; see them with: python review.py --passes")
        return 0, 0

    token = gdocs.get_access_token(
        creds["GOOGLE_CLIENT_ID"], creds["GOOGLE_CLIENT_SECRET"], creds["GOOGLE_REFRESH_TOKEN"])
    today = date.today()
    dispatched = errors = 0
    for record in pending:
        arxiv_id = record["paper"]["arxiv_id"]
        try:
            doc_id, url = gdocs.create_doc(
                token, filename(record, today), render(record, today), creds["GOOGLE_DRIVE_FOLDER_ID"])
        except Exception as exc:
            print(f"  dispatch FAILED {arxiv_id}: {exc}")
            errors += 1
            continue
        db.mark_dispatched(conn, arxiv_id, doc_id, url)
        print(f"  dispatched {arxiv_id} -> {url}")
        dispatched += 1
    return dispatched, errors


async def run(lookback_days: int, max_papers: int, dry_run: bool, verbose: bool = False) -> int:
    config.load_env()
    conn = db.connect(config.STATE_DB)
    run_id = db.start_run(conn)
    ctx = RunContext()
    passed = rejected = failed = 0

    async with ClaudeSDKClient(options=build_options(ctx)) as client:
        print("Ingest")
        await delegate(client, ingest_directive(lookback_days),
                       done=lambda: ctx.candidates is not None or "ingest" in ctx.last_errors,
                       verbose=verbose)
        if ctx.candidates is None:
            reason = ctx.last_errors.get("ingest", "the fetch tool was never called")
            raise RuntimeError(f"ingest produced no candidates: {reason}. "
                               "Rerun with --verbose to see what each agent did.")
        if len(ctx.candidates) >= config.MAX_FETCH:
            print(f"  warning: hit the {config.MAX_FETCH}-paper fetch cap; older papers were not seen")

        new = select_new(conn, ctx.candidates, max_papers)
        print(f"  {len(ctx.candidates)} in window, {len(new)} to extract this run")

        for start in range(0, len(new), config.BATCH_SIZE):
            batch = new[start:start + config.BATCH_SIZE]
            print(f"Extraction batch {start // config.BATCH_SIZE + 1}")
            await delegate(client, extraction_directive(batch),
                           done=lambda: all(p["arxiv_id"] in ctx.extractions for p in batch),
                           verbose=verbose)
            # Persist per batch: a crash later in the run loses at most one batch.
            counts = persist_batch(conn, ctx, batch)
            passed, rejected, failed = passed + counts[0], rejected + counts[1], failed + counts[2]

    print("Dispatch")
    dispatched, dispatch_errors = dispatch_pending(conn, dry_run)

    db.finish_run(conn, run_id, fetched=len(ctx.candidates), attempted=len(new), passed=passed,
                  rejected=rejected, failed=failed, dispatched=dispatched)
    conn.close()
    print(f"Done: {passed} pass, {rejected} reject, {failed} failed, {dispatched} dispatched")

    # Non-zero exit makes a scheduled run show as failed and send the default email.
    all_failed = bool(new) and failed == len(new)
    return 1 if (all_failed or dispatch_errors) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Offshoot pipeline once.")
    parser.add_argument("--lookback-days", type=int, default=config.LOOKBACK_DAYS)
    parser.add_argument("--max-papers", type=int, default=config.MAX_PAPERS_PER_RUN,
                        help="cap on extractions this run (the expensive part)")
    parser.add_argument("--dry-run", action="store_true",
                        help="extract and score, but do not create Google Docs")
    parser.add_argument("--verbose", action="store_true",
                        help="print every agent message, tool call, and task event")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.lookback_days, args.max_papers, args.dry_run, args.verbose)))


if __name__ == "__main__":
    main()
