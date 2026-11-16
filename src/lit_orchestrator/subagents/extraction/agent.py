"""AgentDefinition for the Extraction + Scoring subagent.

One invocation handles one paper. The subagent is stateless: everything it
knows arrives in this system prompt (rubric, two worked examples) or in the
Task prompt the Coordinator writes (the arxiv_id and title).
"""

from __future__ import annotations

import json

from claude_agent_sdk import AgentDefinition

from lit_orchestrator.config import EXTRACTION_MODEL, FIXTURES_DIR, RUBRIC_PATH, SERVER_NAME

EXTRACTION_AGENT_NAME = "extraction"
EXTRACTION_TOOLS = [
    f"mcp__{SERVER_NAME}__fetch_paper_text",
    f"mcp__{SERVER_NAME}__submit_extraction",
]

_INSTRUCTIONS = """\
You are the Extraction subagent of a literature-monitoring pipeline. You are
given one arXiv paper by id. Your job is to read it, draft the best small
project it supports, and judge that project against the rubric below.

Procedure:
1. Call fetch_paper_text with the arxiv_id. If the response says there are
   more parts, fetch each remaining part before continuing. Availability
   statements and limitations are usually near the end.
2. Call submit_extraction once, filling the fields in the order the tool
   lists them. Write evidence before the judgment it supports.
3. If submit_extraction returns problems, fix exactly those and submit again.
4. Finish with a single line: "SUBMITTED <arxiv_id> <verdict>", or
   "FAILED <arxiv_id> <reason>" if a tool told you to stop.

Rules:
- Use only what the paper text says. Do not rely on outside knowledge of the
  paper, its authors, or whether a repository exists.
- Limitations and future-work items are verbatim quotations. Shorten with
  "..." if needed, but do not paraphrase them.
- Never extract from the title or abstract alone when the text fetch fails.
- Do not answer in prose. The submit_extraction call is your answer.
"""


def _example(filename: str) -> str:
    record = json.loads((FIXTURES_DIR / filename).read_text(encoding="utf-8"))
    fields = {"arxiv_id": record["paper"]["arxiv_id"]}
    fields.update({k: v for k, v in record.items() if k != "paper"})
    return json.dumps(fields, indent=2)


def build_extraction_agent() -> AgentDefinition:
    """Built at run time so edits to the rubric file take effect on the next run."""
    prompt = "\n\n".join([
        _INSTRUCTIONS,
        "# RUBRIC (authoritative)\n\n" + RUBRIC_PATH.read_text(encoding="utf-8"),
        "# WORKED EXAMPLES\n\nThese show the shape and level of detail of a "
        "submit_extraction input. They are about other papers; copy nothing from them.",
        "## Example 1: a pass\n\n" + _example("example_draft.json"),
        "## Example 2: a near miss, rejected because the artifacts are not released\n\n"
        + _example("example_reject.json"),
    ])
    return AgentDefinition(
        description=(
            "Reads one arXiv paper by id, drafts a candidate project from it, scores "
            "the project against the rubric, and submits a structured record. "
            "Handles exactly one paper per invocation."
        ),
        prompt=prompt,
        tools=EXTRACTION_TOOLS,
        mcpServers=[SERVER_NAME],
        model=EXTRACTION_MODEL,
        maxTurns=12,
        background=False,
    )
