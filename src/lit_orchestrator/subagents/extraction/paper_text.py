"""Fetch, clean, and cache the full text of an arXiv paper. No LLM involved.

Preference order: LaTeX source (cleanest section structure), then arXiv's
HTML rendering. There is no PDF fallback: it would add a parsing dependency,
and a paper with neither source nor HTML is recorded as a failed extraction.

The reference list is cut in both paths. It is a large share of the tokens
and carries nothing the extraction needs.
"""

from __future__ import annotations

import gzip
import io
import re
import tarfile
import time
from html.parser import HTMLParser
from pathlib import Path

import requests

USER_AGENT = "offshoot/0.1 (personal research monitor)"
REQUEST_DELAY_SECONDS = 3.0  # arXiv's guidance for bursts
_last_request = 0.0

_COMMENT_RE = re.compile(r"(?<!\\)%.*")
_INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")
_BIB_RE = re.compile(r"\\begin\{thebibliography\}|\\bibliography\{|\\printbibliography")


class PaperTextUnavailable(Exception):
    pass


def get_paper_text(arxiv_id: str, cache_dir: Path) -> tuple[str, str]:
    """Return (text, source) where source is 'latex' or 'html'. Cached on disk."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    for source in ("latex", "html"):
        cached = cache_dir / f"{arxiv_id.replace('/', '_')}.{source}.txt"
        if cached.exists():
            return cached.read_text(encoding="utf-8"), source

    for source, fetch in (("latex", _fetch_latex), ("html", _fetch_html)):
        try:
            text = fetch(arxiv_id)
        except (requests.RequestException, tarfile.TarError, OSError, ValueError):
            continue
        if text and len(text) > 2000:  # shorter than this is a stub, not a paper
            path = cache_dir / f"{arxiv_id.replace('/', '_')}.{source}.txt"
            path.write_text(text, encoding="utf-8")
            return text, source
    raise PaperTextUnavailable(f"no LaTeX source or HTML rendering for {arxiv_id}")


def _get(url: str) -> requests.Response:
    """Throttled GET. Callers run in worker threads one at a time (see tools.py)."""
    global _last_request
    wait = REQUEST_DELAY_SECONDS - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    finally:
        _last_request = time.monotonic()
    response.raise_for_status()
    return response


def _fetch_latex(arxiv_id: str) -> str:
    return latex_from_eprint(_get(f"https://arxiv.org/e-print/{arxiv_id}").content)


def latex_from_eprint(payload: bytes) -> str:
    """arXiv serves source as a tarball, a single gzipped .tex, or (no source) a PDF."""
    if payload.startswith(b"%PDF"):
        raise ValueError("PDF-only submission")
    files: dict[str, str] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as tar:
            for member in tar.getmembers():
                if member.isfile() and member.name.endswith(".tex"):
                    files[member.name] = tar.extractfile(member).read().decode("utf-8", "replace")
    except tarfile.ReadError:
        text = gzip.decompress(payload).decode("utf-8", "replace")
        if text.startswith("%PDF"):
            raise ValueError("PDF-only submission")
        files["main.tex"] = text
    if not files:
        raise ValueError("no .tex files in source")

    mains = [name for name, body in files.items() if "\\documentclass" in body]
    main = max(mains or files, key=lambda name: len(files[name]))
    return clean_latex(_expand_inputs(files[main], files, depth=0))


def _expand_inputs(body: str, files: dict[str, str], depth: int) -> str:
    if depth > 5:
        return body

    def replace(match: re.Match) -> str:
        name = match.group(1).strip()
        for candidate in (name, name + ".tex"):
            for path, content in files.items():
                if path == candidate or path.endswith("/" + candidate):
                    return _expand_inputs(content, files, depth + 1)
        return ""

    return _INPUT_RE.sub(replace, _COMMENT_RE.sub("", body))


def clean_latex(text: str) -> str:
    text = _COMMENT_RE.sub("", text)
    start = text.find("\\begin{document}")
    if start != -1:
        text = text[start + len("\\begin{document}"):]
    bib = _BIB_RE.search(text)
    if bib:
        text = text[: bib.start()]
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class _TextExtractor(HTMLParser):
    """Collect visible text, stopping at the bibliography section."""

    _SKIP = {"script", "style", "nav", "header", "footer", "math"}
    _BLOCK = {"p", "div", "section", "h1", "h2", "h3", "h4", "h5", "li", "tr", "br"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0
        self._done = False

    def handle_starttag(self, tag, attrs):
        if "ltx_bibliography" in (dict(attrs).get("class") or ""):
            self._done = True
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._done and not self._skip_depth:
            self.parts.append(data)


def text_from_html(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = re.sub(r"[ \t]+", " ", "".join(parser.parts))
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _fetch_html(arxiv_id: str) -> str:
    return text_from_html(_get(f"https://arxiv.org/html/{arxiv_id}").text)
