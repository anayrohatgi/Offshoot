"""In-process MCP tool exposing arxiv_client to the Ingest subagent."""

import json
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from .arxiv_client import fetch_candidates


@tool(
    "fetch_arxiv_candidates",
    "Fetch candidate arXiv papers submitted within a lookback window, for a "
    "given set of arXiv category codes. Returns metadata only (arxiv_id, "
    "title, abstract, authors, link) — no relevance judgment.",
    {
        "type": "object",
        "properties": {
            "categories": {"type": "array", "items": {"type": "string"}},
            "lookback_days": {"type": "integer"},
            "max_results": {"type": "integer"},
        },
        "required": ["categories"],
    },
)
async def fetch_arxiv_candidates(args: dict[str, Any]) -> dict[str, Any]:
    papers = fetch_candidates(
        categories=args["categories"],
        lookback_days=args.get("lookback_days", 5),
        max_results=args.get("max_results", 100),
    )
    return {"content": [{"type": "text", "text": json.dumps(papers, indent=2)}]}


ingest_tools_server = create_sdk_mcp_server(
    name="ingest-tools",
    version="0.1.0",
    tools=[fetch_arxiv_candidates],
)
