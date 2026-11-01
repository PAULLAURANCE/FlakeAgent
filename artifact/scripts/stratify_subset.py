# -*- coding: utf-8 -*-
"""Stratified model-comparison subset: pick ~50 gate-passed tests.

Proportional to the benchmark's category distribution, RNG-seeded for
reproducibility. Writes data/summary/model50_tests.csv (same columns as
subset.csv), consumed by run_cell.py --rows-file.
"""
import csv
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
SUBSET = os.path.join(HERE, "..", "data", "subset.csv")
GATE = os.path.join(HERE, "..", "data", "gate_results.csv")
OUT = os.path.join(HERE, "..", "data", "summary", "model50_tests.csv")

TARGET = {"od": 13, "td": 16, "nio": 11, "id": 10}  # proportional to 30/36/25/25


def main():
    passed = set()
    with open(GATE, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if str(r.get("pass", "")).lower() == "true":
                passed.add((r["zip"], r["test"]))
    rows = []
    with open(SUBSET, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r["zip"], r["test"]) in passed:
                rows.append(r)
    rng = random.Random(42)
    picked = []
    for cat, k in TARGET.items():
        pool = [r for r in rows if r["category"] == cat]
        rng.shuffle(pool)
        picked.extend(pool[:k])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(picked)
    from collections import Counter
    print("model50 subset:", len(picked), dict(Counter(r["category"] for r in picked)))
    print("written:", OUT)


if __name__ == "__main__":
    main()
