"""Deterministic fetch + parse against the arXiv API. No LLM involved here."""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

BASE_URL = "https://export.arxiv.org/api/query"
USER_AGENT = "lit-orchestrator/0.1 (personal research monitor)"

ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"

_ARXIV_DATE_FMT = "%Y%m%d%H%M"
_ID_VERSION_RE = re.compile(r"v\d+$")


def fetch_candidates(
    categories: list[str],
    lookback_days: int = 5,
    max_results: int = 100,
    page_size: int = 100,
    request_delay_seconds: float = 3.0,
) -> list[dict]:
    """Return metadata-only candidates from arXiv, newest first.

    categories: arXiv category codes, e.g. ["cs.AI", "cs.LG"].
    lookback_days: how many days back (from now, UTC) to search.
    max_results: hard cap on papers returned across all pages.
    page_size: arXiv results per HTTP request (arXiv caps this around 2000;
        keep it small since we're paging a short lookback window, not
        crawling the archive).
    request_delay_seconds: pause between paginated requests, per arXiv's
        usage guidance of ~3s between calls in a burst.
    """
    search_query = _build_search_query(categories, lookback_days)

    papers: list[dict] = []
    start = 0
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    while len(papers) < max_results:
        batch_size = min(page_size, max_results - len(papers))
        params = {
            "search_query": search_query,
            "start": start,
            "max_results": batch_size,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        response = session.get(BASE_URL, params=params, timeout=30)
        response.raise_for_status()

        entries = _parse_feed(response.text)
        if not entries:
            break

        papers.extend(entries)
        start += len(entries)

        if len(entries) < batch_size:
            break  # fewer results than asked for means we've hit the end

        time.sleep(request_delay_seconds)

    return papers[:max_results]


def _build_search_query(categories: list[str], lookback_days: int) -> str:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=lookback_days)

    cat_clause = " OR ".join(f"cat:{c}" for c in categories)
    date_clause = (
        f"submittedDate:[{start.strftime(_ARXIV_DATE_FMT)}"
        f" TO {now.strftime(_ARXIV_DATE_FMT)}]"
    )
    return f"({cat_clause}) AND {date_clause}"


def _parse_feed(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    return [_parse_entry(entry) for entry in root.findall(f"{ATOM_NS}entry")]


def _parse_entry(entry: ET.Element) -> dict:
    raw_id = _text(entry, f"{ATOM_NS}id")
    arxiv_id = _ID_VERSION_RE.sub("", raw_id.rsplit("/abs/", 1)[-1])

    authors = [
        _text(author, f"{ATOM_NS}name")
        for author in entry.findall(f"{ATOM_NS}author")
    ]

    primary_category_el = entry.find(f"{ARXIV_NS}primary_category")
    primary_category = (
        primary_category_el.get("term") if primary_category_el is not None else None
    )

    return {
        "arxiv_id": arxiv_id,
        "title": _clean_whitespace(_text(entry, f"{ATOM_NS}title")),
        "abstract": _clean_whitespace(_text(entry, f"{ATOM_NS}summary")),
        "authors": authors,
        "link": f"https://arxiv.org/abs/{arxiv_id}",
        "published": _text(entry, f"{ATOM_NS}published"),
        "primary_category": primary_category,
    }


def _text(element: ET.Element, tag: str) -> str:
    child = element.find(tag)
    return child.text.strip() if child is not None and child.text else ""


def _clean_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
