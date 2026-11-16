"""Check the rubric against your own judgment.

Every extraction is stored in state.db whether it passed or not, so
calibration needs no extra model calls: export drafts, label them by hand
without seeing the model's gates, then compare.

    python calibrate.py export -n 35
        writes calibration/drafts.md (read this) and calibration/labels.jsonl (fill this in)
    python calibrate.py compare
        prints where your labels and the model's gates disagree

In labels.jsonl set "my_verdict" to "pass" or "reject" on each line, and
optionally "my_compute_gate", "my_tractability", and "note". Then edit the
anchors in docs/relevance-criteria.md where the disagreements cluster.

The calibration/ folder is gitignored and is never read by the pipeline.
"""

from __future__ import annotations

import argparse
import json
from datetime import date

from lit_orchestrator import config
from lit_orchestrator.dispatch.render import render
from lit_orchestrator.state import db

CALIBRATION_DIR = config.REPO_ROOT / "calibration"
DRAFTS = CALIBRATION_DIR / "drafts.md"
LABELS = CALIBRATION_DIR / "labels.jsonl"
_HIDDEN = ("disqualifier", "compute_gate", "tractability", "verdict")


def _blind(record: dict) -> dict:
    """Mask the model's judgments so they cannot anchor the hand label."""
    return {**record, **{key: "(hidden)" for key in _HIDDEN}}


def export(n: int) -> None:
    conn = db.connect(config.STATE_DB)
    labelled = set()
    if LABELS.exists():
        labelled = {json.loads(line)["arxiv_id"] for line in LABELS.read_text().splitlines() if line.strip()}
    rows = conn.execute("SELECT arxiv_id, record_json FROM papers WHERE status = 'extracted' "
                        "ORDER BY first_seen_at").fetchall()
    conn.close()
    todo = [json.loads(r["record_json"]) for r in rows if r["arxiv_id"] not in labelled][:n]
    if not todo:
        print("no unlabelled extractions in state.db; run the pipeline first")
        return

    CALIBRATION_DIR.mkdir(exist_ok=True)
    with DRAFTS.open("a", encoding="utf-8") as drafts, LABELS.open("a", encoding="utf-8") as labels:
        for record in todo:
            drafts.write(f"\n\n---\n\n```\n{render(_blind(record), date.today())}```\n")
            labels.write(json.dumps({
                "arxiv_id": record["paper"]["arxiv_id"], "my_verdict": None,
                "my_compute_gate": None, "my_tractability": None, "note": "",
            }) + "\n")
    print(f"exported {len(todo)} drafts. Read {DRAFTS} and fill in {LABELS}")


def compare() -> None:
    if not LABELS.exists():
        print("nothing to compare; run `python calibrate.py export` first")
        return
    conn = db.connect(config.STATE_DB)
    agree = total = model_pass = true_pass = 0
    for line in LABELS.read_text().splitlines():
        label = json.loads(line) if line.strip() else {}
        if label.get("my_verdict") not in ("pass", "reject"):
            continue
        row = conn.execute("SELECT record_json FROM papers WHERE arxiv_id = ?", (label["arxiv_id"],)).fetchone()
        if row is None or row["record_json"] is None:
            continue
        record = json.loads(row["record_json"])
        total += 1
        agree += record["verdict"] == label["my_verdict"]
        model_pass += record["verdict"] == "pass"
        true_pass += record["verdict"] == "pass" and label["my_verdict"] == "pass"

        diffs = [f"verdict model={record['verdict']} you={label['my_verdict']}"] \
            if record["verdict"] != label["my_verdict"] else []
        for field in ("compute_gate", "tractability"):
            mine = label.get(f"my_{field}")
            if mine and mine != record[field]:
                diffs.append(f"{field} model={record[field]} you={mine}")
        if diffs:
            print(f"{label['arxiv_id']}: " + "; ".join(diffs))
            if record["disqualifier"]:
                print(f"    model disqualifier: {record['disqualifier']}")
            if label.get("note"):
                print(f"    your note: {label['note']}")
    conn.close()

    if not total:
        print("no labelled lines yet: set my_verdict in", LABELS)
        return
    print(f"\nlabelled: {total}   verdict agreement: {agree}/{total}")
    # Accuracy is misleading at a ~1% accept rate (rejecting everything scores 99%),
    # so the number to watch is precision on the model's accepts.
    print(f"precision on model accepts: {true_pass}/{model_pass}" if model_pass
          else "the model accepted none of the labelled drafts")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("export").add_argument("-n", type=int, default=35)
    sub.add_parser("compare")
    args = parser.parse_args()
    export(args.n) if args.command == "export" else compare()


if __name__ == "__main__":
    main()
