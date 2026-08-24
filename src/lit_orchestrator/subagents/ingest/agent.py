"""AgentDefinition for the Ingest subagent.

This only defines the subagent (its prompt, its tool access).
The Coordinator invokes it via the Task tool in the lit_orchestrator.coordinator.
"""

from claude_agent_sdk import AgentDefinition
from lit_orchestrator.subagents.ingest.tools import ingest_tools_server

INGEST_AGENT_NAME = "ingest"


ingest_agent = AgentDefinition(
    description=(
        "Fetches candidate arXiv papers within a lookback window. "
        "Metadata only — no relevance judgment, no extraction."
    ),
    prompt=(
        "You are the Ingest subagent for a literature-monitoring tool.\n\n"
        "You will be told: a list of arXiv category codes, a lookback window in days, and a max_results cap.\n\n"
        "Call the fetch_arxiv_candidates tool exactly once with those arguments. "
        "Then return its output verbatim as your final answer: the JSON array of paper objects, unmodified. "
        "Do not summarize, filter, rank, or comment on the papers. Do not judge relevance. "
        "If the tool returns an empty list, return an empty JSON array."
    ),
    tools=None,
    mcpServers=["ingest-tools"],

    model="haiku", 
    maxTurns = 3
)
