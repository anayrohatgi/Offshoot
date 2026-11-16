"""Read-only views of state.db for the weekly read-through.

    python review.py                 recent rejects with the reason each was blocked
    python review.py --passes        accepted drafts and their Doc links
    python review.py --failed        papers whose extraction failed
    python review.py --runs          recent runs (a blank 'finished' means it crashed)
    python review.py --id 2609.19453 the full draft for one paper
"""

from __future__ import annotations

import argparse
import json
from datetime import date

from lit_orchestrator import config
from lit_orchestrator.dispatch.render import render
from lit_orchestrator.state import db


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--passes", action="store_true")
    group.add_argument("--failed", action="store_true")
    group.add_argument("--runs", action="store_true")
    group.add_argument("--id")
    parser.add_argument("-n", type=int, default=30, help="rows to show (default 30)")
    args = parser.parse_args()
    conn = db.connect(config.STATE_DB)

    if args.id:
        row = conn.execute("SELECT record_json, error FROM papers WHERE arxiv_id = ?", (args.id,)).fetchone()
        if row is None:
            print(f"{args.id} is not in state.db")
        elif row["record_json"] is None:
            print(f"{args.id} failed extraction: {row['error']}")
        else:
            print(render(json.loads(row["record_json"]), date.today(), include_disqualifier=True))
    elif args.runs:
        for r in conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (args.n,)):
            print(f"{r['started_at']}  finished={r['finished_at'] or '-':25}  fetched={r['fetched']} "
                  f"attempted={r['attempted']} pass={r['passed']} reject={r['rejected']} "
                  f"failed={r['failed']} dispatched={r['dispatched']}")
    elif args.failed:
        for r in conn.execute("SELECT arxiv_id, attempts, error, title FROM papers "
                              "WHERE status = 'failed' ORDER BY updated_at DESC LIMIT ?", (args.n,)):
            print(f"{r['arxiv_id']}  attempts={r['attempts']}  {r['error']}\n    {r['title']}")
    else:
        verdict = "pass" if args.passes else "reject"
        rows = conn.execute("SELECT record_json, doc_url FROM papers WHERE verdict = ? "
                            "ORDER BY updated_at DESC LIMIT ?", (verdict, args.n)).fetchall()
        for r in rows:
            record = json.loads(r["record_json"])
            paper = record["paper"]
            print(f"{paper['arxiv_id']}  compute={record['compute_gate']}  "
                  f"tractability={record['tractability']}\n    {paper['title']}")
            print(f"    {r['doc_url'] or 'not dispatched yet'}" if args.passes
                  else f"    {record['disqualifier'] or 'no disqualifier; failed a gate'}")
        if not rows:
            print(f"no {verdict} records yet")
    conn.close()


if __name__ == "__main__":
    main()
