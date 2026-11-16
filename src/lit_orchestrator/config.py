"""Paths, feed settings, and environment handling. No secrets live here."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_DB = REPO_ROOT / "state.db"
CACHE_DIR = REPO_ROOT / "cache"
RUBRIC_PATH = REPO_ROOT / "docs" / "relevance-criteria.md"
FIXTURES_DIR = REPO_ROOT / "fixtures"

# A paper qualifies when it carries at least one category from EACH list.
# The q-bio subcategories are enumerated rather than written as "q-bio.*" so
# the query does not depend on arXiv's wildcard handling.
BIO_CATEGORIES = [
    "q-bio.BM", "q-bio.CB", "q-bio.GN", "q-bio.MN", "q-bio.NC",
    "q-bio.OT", "q-bio.PE", "q-bio.QM", "q-bio.SC", "q-bio.TO",
]
ML_CATEGORIES = ["cs.LG", "cs.AI"]

LOOKBACK_DAYS = 5        # fixed window; dedup against state.db makes reruns safe
MAX_FETCH = 300          # metadata rows per run (cheap)
MAX_PAPERS_PER_RUN = 25  # extractions per run (the expensive part)
BATCH_SIZE = 5           # extraction subagents launched in parallel per batch
MAX_ATTEMPTS = 2         # runs that may try a paper before it is given up on

SERVER_NAME = "offshoot"
COORDINATOR_MODEL = "sonnet"
EXTRACTION_MODEL = "sonnet"   # the main cost driver; "haiku" is cheaper and less careful

_ENV_KEYS = (
    "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN",
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REFRESH_TOKEN", "GOOGLE_DRIVE_FOLDER_ID",
)


def load_env() -> None:
    """Load .env, then drop empty values.

    GitHub Actions expands an unset secret to "", and an empty
    ANTHROPIC_API_KEY would shadow a valid CLAUDE_CODE_OAUTH_TOKEN.
    """
    load_dotenv(REPO_ROOT / ".env")
    for key in _ENV_KEYS:
        if os.environ.get(key) == "":
            del os.environ[key]


def google_credentials() -> dict[str, str] | None:
    """Return the four Google settings, or None if any is missing."""
    keys = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
            "GOOGLE_REFRESH_TOKEN", "GOOGLE_DRIVE_FOLDER_ID")
    values = {k: os.environ.get(k) for k in keys}
    return values if all(values.values()) else None
