"""In-process MCP tools for the Extraction subagent.

fetch_paper_text lets the subagent resolve an arxiv_id into text itself, so
full papers never pass through the Coordinator's context.

submit_extraction is the structured-output channel. Its input schema is the
extraction schema, so the model's answer is a tool call that the API shapes
to that schema, and the handler below is the validation-retry loop: an
invalid submission is returned as a tool error naming what to fix, and the
subagent submits again.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from claude_agent_sdk import SdkMcpTool, tool

from lit_orchestrator.run_context import RunContext

from .paper_text import PaperTextUnavailable, get_paper_text
from .schema import EXTRACTION_SCHEMA, build_record, validate_extraction

PART_CHARS = 50_000   # keeps one tool result well inside the CLI's MCP output limit
MAX_PARTS = 3         # ~150k characters; later appendices are dropped
MAX_SUBMIT_ATTEMPTS = 3


def _text(message: str, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": message}]}
    if is_error:
        result["is_error"] = True
    return result


def build_extraction_tools(ctx: RunContext, cache_dir: Path) -> list[SdkMcpTool[Any]]:
    fetch_lock = asyncio.Lock()  # parallel subagents share one arXiv rate limit

    @tool(
        "fetch_paper_text",
        "Return the full text of an arXiv paper with the reference list removed. "
        "Long papers come in parts: the response states 'part N of M'; call again "
        "with the next part number until you have read every part.",
        {
            "type": "object",
            "properties": {
                "arxiv_id": {"type": "string"},
                "part": {"type": "integer", "minimum": 1},
            },
            "required": ["arxiv_id"],
        },
    )
    async def fetch_paper_text(args: dict[str, Any]) -> dict[str, Any]:
        arxiv_id = args["arxiv_id"]
        try:
            async with fetch_lock:
                text, source = await asyncio.to_thread(get_paper_text, arxiv_id, cache_dir)
        except PaperTextUnavailable as exc:
            ctx.last_errors[arxiv_id] = str(exc)
            return _text(f"{exc}. Do not extract from the abstract. Reply FAILED.", is_error=True)

        parts = [text[i:i + PART_CHARS] for i in range(0, len(text), PART_CHARS)][:MAX_PARTS]
        part = args.get("part", 1)
        if not 1 <= part <= len(parts):
            return _text(f"part must be between 1 and {len(parts)}", is_error=True)
        return _text(f"[{arxiv_id} | source: {source} | part {part} of {len(parts)}]\n\n{parts[part - 1]}")

    @tool(
        "submit_extraction",
        "Submit the finished extraction and verdict for one paper. Fill the fields "
        "in the order given. If the response lists problems, fix them and submit again.",
        EXTRACTION_SCHEMA,
    )
    async def submit_extraction(args: dict[str, Any]) -> dict[str, Any]:
        arxiv_id = args.get("arxiv_id", "")
        paper = ctx.paper(arxiv_id)
        if paper is None:
            return _text(f"arxiv_id {arxiv_id!r} is not a paper in this run. Use the id you were given.",
                         is_error=True)
        if arxiv_id in ctx.extractions:
            return _text("Already accepted. Reply SUBMITTED.")

        if ctx.submit_attempts.get(arxiv_id, 0) >= MAX_SUBMIT_ATTEMPTS:
            return _text("The attempt limit is reached. Reply FAILED.", is_error=True)

        attempt = ctx.submit_attempts.get(arxiv_id, 0) + 1
        ctx.submit_attempts[arxiv_id] = attempt
        problems = validate_extraction(args, expected_arxiv_id=arxiv_id)
        if not problems:
            ctx.extractions[arxiv_id] = build_record(paper, args)
            ctx.last_errors.pop(arxiv_id, None)
            return _text(f"Accepted. Reply: SUBMITTED {arxiv_id} {args['verdict']}")

        listing = "\n".join(f"- {p}" for p in problems)
        ctx.last_errors[arxiv_id] = f"invalid after {attempt} attempt(s): {problems[0]}"
        if attempt >= MAX_SUBMIT_ATTEMPTS:
            return _text(f"Rejected, and the attempt limit is reached. Reply FAILED.\n{listing}",
                         is_error=True)
        return _text(f"Rejected ({attempt} of {MAX_SUBMIT_ATTEMPTS} attempts used). "
                     f"Fix these and submit again:\n{listing}", is_error=True)

    return [fetch_paper_text, submit_extraction]
