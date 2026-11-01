# -*- coding: utf-8 -*-
"""Drop all TD rows from gate_results.csv so they are re-gated with the
correct dataset mechanism (FlakyCodeChange.patch sleep injection), which
replaced the earlier isolated-rerun protocol.
"""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "..", "data", "gate_results.csv")

rows = []
dropped = []
with open(GATE, encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r.get("category") == "td":
            dropped.append((r["zip"], r["test"].split("#")[-1]))
        else:
            rows.append(r)

with open(GATE, "w", newline="", encoding="utf-8") as f:
    if rows:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

print("dropped %d td rows:" % len(dropped))
for d in dropped:
    print("  ", d)
print("kept %d rows" % len(rows))
