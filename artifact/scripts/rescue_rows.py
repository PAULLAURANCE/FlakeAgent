# -*- coding: utf-8 -*-
"""Rescue pass prep: delete gate rows that should be re-run.

Deletes from gate_results.csv: (a) BUILD_FAILED rows (X11 libs fixed),
(b) rows with 'exc' notes (transient errors; driver/gate hardened since),
(c) ALL non-pass rows — the pre-fix gate evaluated OD/ID with broken
mechanisms (default surefire instead of the dataset's custom one; gate_id
timeout bug) and TD at n=40 instead of the dataset's n=100.
Keeps pass=True rows (resume keys).
"""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "..", "data", "gate_results.csv")

rows = []
deleted = []
with open(GATE, encoding="utf-8") as f:
    for r in csv.DictReader(f):
        notes = r.get("notes", "") or ""
        if str(r.get("pass", "")).lower() != "true":
            # a TD row already gated at the dataset protocol (n>=100) is a
            # FINAL verdict — keep it. Pre-fix TD rows used n=40, so they
            # (n_runs<100) are still re-gated.
            if r.get("category") == "td" and int(r.get("n_runs", 0) or 0) >= 100:
                rows.append(r)
                continue
            deleted.append((r["zip"], r["test"].split("#")[-1], notes or r["category"]))
        else:
            rows.append(r)

with open(GATE, "w", newline="", encoding="utf-8") as f:
    if rows:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

print("deleted %d rows:" % len(deleted))
for d in deleted:
    print("  ", d)
print("kept %d rows" % len(rows))
