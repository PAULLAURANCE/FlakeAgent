# -*- coding: utf-8 -*-
"""reset_td_and_make_rerun: drop contaminated TD rows from the main results and
emit a rows-file for re-running them with clean bytecode.

The TD gate left stale injected bytecode (see clean_td_bytecode.py); the 31
gate-passed TD rows in agent_ds-flash.jsonl are therefore spurious and must be
removed before the clean re-run appends honest rows.

Run from WSL: python3 scripts/reset_td_and_make_rerun.py
"""
import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SUBSET = os.path.join(ROOT, "data", "subset.csv")
GATE = os.path.join(ROOT, "data", "gate_results.csv")
RES = os.path.join(ROOT, "data", "results", "agent_ds-flash.jsonl")
ROWSFILE = os.path.join(ROOT, "data", "td_rerun.csv")


def main():
    passed = {(r["zip"], r["test"]) for r in csv.DictReader(open(GATE, encoding="utf-8"))
              if str(r.get("pass", "")).lower() == "true"}
    td = [r for r in csv.DictReader(open(SUBSET, encoding="utf-8"))
          if r["category"] == "td" and (r["zip"], r["test"]) in passed]
    with open(ROWSFILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["zip", "test"])
        for r in sorted(td, key=lambda x: x["zip"]):
            w.writerow([r["zip"], r["test"]])
    print("[reset] td_rerun.csv rows:", len(td), flush=True)

    rows = [json.loads(l) for l in open(RES, encoding="utf-8")]
    keep = [r for r in rows if r.get("category_gt") != "td"]
    with open(RES, "w", encoding="utf-8") as f:
        for r in keep:
            f.write(json.dumps(r) + "\n")
    print("[reset] removed %d TD rows, kept %d" % (len(rows) - len(keep), len(keep)), flush=True)


if __name__ == "__main__":
    main()
