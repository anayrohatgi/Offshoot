"""In-process MCP tool exposing arxiv_client to the Ingest subagent."""

from __future__ import annotations

import asyncio
from typing import Any

from claude_agent_sdk import SdkMcpTool, tool

from lit_orchestrator.run_context import RunContext

from .arxiv_client import fetch_candidates


def build_ingest_tools(ctx: RunContext) -> list[SdkMcpTool[Any]]:
    @tool(
        "fetch_arxiv_candidates",
        "Fetch metadata for arXiv papers submitted within a lookback window that "
        "carry at least one category from each of two lists. Stores the result "
        "for the coordinator and returns only a count. No relevance judgment.",
        {
            "type": "object",
            "properties": {
                "bio_categories": {"type": "array", "items": {"type": "string"}},
                "ml_categories": {"type": "array", "items": {"type": "string"}},
                "lookback_days": {"type": "integer"},
                "max_results": {"type": "integer"},
            },
            "required": ["bio_categories", "ml_categories", "lookback_days", "max_results"],
        },
    )
    async def fetch_arxiv_candidates(args: dict[str, Any]) -> dict[str, Any]:
        try:
            # requests is blocking; keep the SDK's event loop free.
            papers = await asyncio.to_thread(
                fetch_candidates,
                bio_categories=args["bio_categories"],
                ml_categories=args["ml_categories"],
                lookback_days=args["lookback_days"],
                max_results=args["max_results"],
            )
        except Exception as exc:  # network or XML failure: report, don't crash the run
            ctx.last_errors["ingest"] = f"arXiv fetch failed: {exc}"
            return {"content": [{"type": "text", "text": f"arXiv fetch failed: {exc}"}],
                    "is_error": True}
        ctx.candidates = papers
        return {"content": [{"type": "text", "text": f"Stored {len(papers)} candidates."}]}

    return [fetch_arxiv_candidates]
