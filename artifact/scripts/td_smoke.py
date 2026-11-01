# -*- coding: utf-8 -*-
"""Smoke test: run the new TD gate (sleep-injection patch) on one test."""
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "executor"))
import config
import gate

ZIP = sys.argv[1] if len(sys.argv) > 1 else "CURATOR-681"

subset = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "subset.csv")
row = next(r for r in csv.DictReader(open(subset, encoding="utf-8")) if r["zip"] == ZIP)
module = row["module"] or "."
env_path = os.path.join(config.WORKDIR, ZIP, "build.env")
info = json.load(open(env_path, encoding="utf-8"))
print("build_ok=%s java=%s module=%s" % (info["build_ok"], info["java"], module))
print("test=%s" % row["test"])

ctx = {"flaky_dir": info["flaky_dir"], "module": module, "test": row["test"],
       "java": info["java"], "repo_local": info.get("repo_local"), "zip": ZIP,
       "gate_runs": 3}
t0 = time.time()
res = gate.gate_td(ctx, t0 + 3600)
print("RESULT: %s  (%.1fs)" % (res, time.time() - t0))
