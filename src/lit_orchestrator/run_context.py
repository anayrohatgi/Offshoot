"""Per-run result channel between subagent tools and the Coordinator.

Subagents return their work by calling a tool, and the tool handler (which
runs in this Python process) writes the validated result here. The
Coordinator reads it after the Task call returns. This replaces parsing JSON
out of a subagent's final chat message, which is the fragile alternative.

It is not shared memory between agents: no subagent can read it, and nothing
a subagent needs is ever placed in it for them to find.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunContext:
    candidates: list[dict] | None = None                       # set by ingest
    extractions: dict[str, dict] = field(default_factory=dict)  # arxiv_id -> record
    submit_attempts: dict[str, int] = field(default_factory=dict)
    last_errors: dict[str, str] = field(default_factory=dict)   # arxiv_id -> why it failed

    def paper(self, arxiv_id: str) -> dict | None:
        for candidate in self.candidates or []:
            if candidate["arxiv_id"] == arxiv_id:
                return candidate
        return None
