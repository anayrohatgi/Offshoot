import json
from datetime import date

from lit_orchestrator import config
from lit_orchestrator.dispatch.gdocs import build_upload_body
from lit_orchestrator.dispatch.render import filename, render

DAY = date(2026, 11, 16)


def load(name):
    return json.loads((config.FIXTURES_DIR / name).read_text())


def test_filename_is_stable_and_bounded():
    name = filename(load("example_draft.json"), DAY)
    assert name == "2026-11-16_2609.19453_sharpness-aware-minimization-sam-improve"
    assert name == filename(load("example_draft.json"), DAY)


def test_render_pass():
    text = render(load("example_draft.json"), DAY)
    assert "Verdict    PASS  ·  compute: fits_free_colab  ·  tractability: deliverable_named" in text
    assert "Kaitlin Zareno et al." in text
    assert "1 NVIDIA T4 GPU.  [3.2]" in text       # evidence is rendered with its section
    assert "3. Report whether" in text
    assert "Future work" not in text               # empty list: section omitted, no N/A
    assert "NOTES" not in text                     # null fixed_date_note
    assert "pp" not in text.splitlines()[2]        # null page count omitted from the header


def test_disqualifier_only_shown_on_request():
    record = load("example_reject.json")
    assert "artifacts_unreleased" not in render(record, DAY)
    assert "Blocked    artifacts_unreleased" in render(record, DAY, include_disqualifier=True)
    assert "Qingyang Xu ·" in render(record, DAY)  # single author: no "et al."


def test_upload_body_is_well_formed_multipart():
    body = build_upload_body("name", "héllo", "folder123").decode("utf-8")
    assert body.count("--offshoot-boundary-7f3a9c") == 3 and body.endswith("--\r\n")
    assert '"parents": ["folder123"]' in body and "application/vnd.google-apps.document" in body
    assert "héllo" in body
