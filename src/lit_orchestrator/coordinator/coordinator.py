import json
import re
from claude_agent_sdk import TERMINAL_TASK_STATUSES, AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, TextBlock
from claude_agent_sdk import TaskStartedMessage, TaskNotificationMessage, TaskUpdatedMessage, AssistantMessage, TextBlock
from lit_orchestrator.subagents.ingest.agent import ingest_agent
from lit_orchestrator.subagents.ingest.tools import ingest_tools_server
from lit_orchestrator.state.db import get_connection, is_seen, mark_seen
# from lit_orchestrator.subagents.relevance.agent import relevance_agent
# from lit_orchestrator.subagents.extraction.agent import extraction_agents
import asyncio

categories = ["cs.AI", "cs.LG"]
lookback_days = 2
max_results = 20

async def perform_ingest(categories, lookback_days, max_results):
    """Perform the ingest subagent task and return the result."""

    directive = (
    "Call the task tool exactly once, invoking the ingest subagent. "
    f"In the Task prompt, tell it: categories={categories}, "
    f"lookback_days={lookback_days}, max_results={max_results}. "
    "Take no other action."
    )
    options = ClaudeAgentOptions(
    agents = {"ingest": ingest_agent},
    mcp_servers = {"ingest-tools": ingest_tools_server},
    strict_mcp_config = False,
    allowed_tools = ["Task"],
    permission_mode="bypassPermissions"
    )
    async with ClaudeSDKClient(options = options) as client:
        await client.query(directive)
        task_tool_use_id = None
        target_task_id = None
        last_subagent_text = None

        async for message in client.receive_messages():
            if isinstance(message, TaskStartedMessage):
               target_task_id = message.task_id
               task_tool_use_id = message.tool_use_id
            elif isinstance(message, TaskNotificationMessage):
                if message.task_id == target_task_id:
                    break
            elif isinstance(message, TaskUpdatedMessage):
                if message.task_id == target_task_id and message.status in TERMINAL_TASK_STATUSES:
                    break
            elif isinstance(message, AssistantMessage) and task_tool_use_id is not None and message.parent_tool_use_id == task_tool_use_id:
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        last_subagent_text = block.text
        if last_subagent_text is None:
            raise RuntimeError(
            "Ingest subagent completed without producing a final text answer "
            f"(hit maxTurns or errored out; task status reporting is limited here)."
            )
        papers = json.loads(strip_code_fences(last_subagent_text))
        return papers

def strip_code_fences(text: str) -> str:
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text

def filter_new_papers(conn, papers):
    new_papers = []
    for paper in papers:
        if is_seen(conn, paper["arxiv_id"]):
            continue
        mark_seen(conn, paper["arxiv_id"])
        new_papers.append(paper)
    return new_papers

 
if __name__ == "__main__":
    conn = get_connection()
    papers = asyncio.run(perform_ingest(categories, lookback_days, max_results))
    new_papers = filter_new_papers(conn, papers)
    print(new_papers)
    conn.close()

    



