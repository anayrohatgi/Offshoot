"""AgentDefinition for the Ingest subagent.

Deterministic fetch with no LLM judgment. It is still a subagent, invoked by
the Coordinator through the Task tool, so every stage is delegated the same way.
"""

from claude_agent_sdk import AgentDefinition

from lit_orchestrator.config import SERVER_NAME

INGEST_AGENT_NAME = "ingest"
INGEST_TOOL = f"mcp__{SERVER_NAME}__fetch_arxiv_candidates"

ingest_agent = AgentDefinition(
    description=(
        "Fetches candidate arXiv paper metadata for a lookback window. "
        "Metadata only: no relevance judgment, no extraction."
    ),
    prompt=(
        "You are the Ingest subagent of a literature-monitoring pipeline.\n\n"
        "You will be given two lists of arXiv category codes, a lookback window "
        "in days, and a max_results cap. Call fetch_arxiv_candidates exactly once "
        "with exactly those values. The tool stores the papers itself.\n\n"
        "Then reply with one line: the tool's response text. Do not list, "
        "summarise, filter, or judge papers. If the tool reports an error, call "
        "it one more time; if it fails again, reply with the error text."
    ),
    tools=[INGEST_TOOL],
    mcpServers=[SERVER_NAME],
    model="haiku",
    maxTurns=4,
    background=False,
)
