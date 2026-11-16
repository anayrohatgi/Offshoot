import gzip
import io
import tarfile

import pytest

from lit_orchestrator.subagents.extraction.paper_text import latex_from_eprint, text_from_html

MAIN = r"""\documentclass{article}
\begin{document}
\section{Intro} Real text. % a comment
We keep 50\% here.
\input{sections/method}
\bibliography{refs}
\appendix after the references
\end{document}"""


def tarball(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, body in files.items():
            data = body.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_tarball_inlines_inputs_and_cuts_references():
    text = latex_from_eprint(tarball({"main.tex": MAIN, "sections/method.tex": "Method body.", "refs.bib": "@x"}))
    assert "Real text." in text and "Method body." in text
    assert "a comment" not in text
    assert r"50\% here" in text                    # escaped percent is not a comment
    assert "bibliography" not in text and "after the references" not in text


def test_single_gzipped_tex():
    assert "Real text." in latex_from_eprint(gzip.compress(MAIN.encode()))


def test_pdf_only_submission_is_refused():
    with pytest.raises(ValueError):
        latex_from_eprint(b"%PDF-1.5 ...")


def test_html_stops_at_bibliography():
    html = ('<html><head><style>p{}</style></head><body><h2>1 Intro</h2><p>Body text.</p>'
            '<section class="ltx_bibliography"><h2>References</h2><li>Ref one</li></section></body></html>')
    text = text_from_html(html)
    assert "Body text." in text and "Ref one" not in text and "p{}" not in text
