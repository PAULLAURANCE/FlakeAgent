# -*- coding: utf-8 -*-
"""run_cell: main FlakeAgent experiment orchestrator.

For each subset test that passed the validation gate: prepare the project
(cached build.env), then run the bounded agent loop with the chosen model.

Usage (inside WSL):
  python3 .../run_cell.py --model ds-flash [--only ZIP] [--limit N]
      [--seed 0] [--ablation none|noreflection|space4|nosource|warm]
      [--workers 2] [--max-calls 6] [--skip-gate-file PATH]

Writes data/results/agent_<model>[_<ablation>][_s<seed>].jsonl (one JSON/test).
"""
import csv
import json
import os
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "executor"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
import config
import prepare
import loop as agent_loop

SUBSET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "subset.csv")
RESDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "results")
GATE_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "gate_results.csv")


def log(msg):
    print("[cell %s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def load_rows(only, limit, gate_passed_only, skip_gate_file=None):
    rows = []
    with open(SUBSET, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    if only:
        rows = [r for r in rows if r["zip"] == only]
    if limit:
        rows = rows[:limit]
    if gate_passed_only:
        gate = skip_gate_file or GATE_CSV
        passed = set()
        if os.path.exists(gate):
            with open(gate, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    if str(r.get("pass", "")).lower() == "true":
                        passed.add((r["zip"], r["test"]))
        rows = [r for r in rows if (r["zip"], r["test"]) in passed]
    return rows


def one_test(args):
    """Worker entry: (row, model, ablation, seed, max_calls, out_path, warm_gate)."""
    row, model, ablation, seed, max_calls, out_path, warm_gate = args
    zipname, module, test = row["zip"], row["module"] or ".", row["test"]
    env_path = os.path.join(config.WORKDIR, zipname, "build.env")
    if not os.path.exists(env_path):
        info, tail = prepare.prepare(zipname, module, row["java"] or None)
        log("%s build_ok=%s" % (zipname, info["build_ok"]))
        if not info["build_ok"]:
            with open(out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"zip": zipname, "test": test, "model": model,
                                    "error": "BUILD_FAILED", "reproduced": False,
                                    "ablation": ablation, "seed": seed}) + "\n")
            return
    with open(env_path, encoding="utf-8") as f:
        info = json.load(f)
    if not info.get("build_ok"):
        return
    ctx = {"flaky_dir": info["flaky_dir"], "module": module, "test": test,
           "java": info["java"], "repo_local": info.get("repo_local"), "zip": zipname,
           "category_gt": row["category"]}
    warm_failure = None
    if ablation == "warm":
        warm_failure = warm_failure_for(row, info)
        if warm_failure is None:
            log("%s warm: official mechanism did not fail in 1 try, skipping" % test)
            return
    t0 = time.time()
    try:
        r = agent_loop.run_agent(ctx, model, out_path, ablation=ablation,
                                 warm_failure=warm_failure, seed=seed,
                                 max_calls=max_calls)
    except Exception as e:
        import traceback
        log("%s %s#%s -> CRASH: %s" % (model, zipname, test.split("#")[-1], e))
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"zip": zipname, "test": test, "model": model,
                                "ablation": ablation, "seed": seed,
                                "reproduced": False, "error": "CRASH: %s" % e,
                                "traceback": traceback.format_exc()[-2000:]}) + "\n")
        return
    log("%s %s#%s -> %s (%.0fs, %d calls, %d execs)" % (
        model, zipname, test.split("#")[-1],
        "REPRO" if r["reproduced"] else "no", time.time() - t0,
        r["llm_calls"], r["executions"]))


def warm_failure_for(row, info):
    """Run the official mechanism once; return the failed-entry list for warm start."""
    import gate as g
    import junit_driver as jd
    ctx = {"flaky_dir": info["flaky_dir"], "module": row["module"] or ".",
           "test": row["test"], "java": info["java"], "repo_local": info.get("repo_local"),
           "zip": row["zip"]}
    cat = row["category"]
    obs = None
    try:
        if cat == "od":
            spec = ("%s,%s" % (row.get("polluter"), row["test"])
                    if row.get("polluter") else row["test"])
            obs = jd.run_ordered(ctx["flaky_dir"], ctx["module"], spec,
                                 strategy="WARM-OD", params={}, java=ctx["java"],
                                 repo_local=ctx.get("repo_local"))
        elif cat == "nio":
            ok, flaky, obs = g._nio_iteration(ctx)
            if not flaky:
                return None
        elif cat == "id":
            args = ["-pl", ctx["module"], "edu.illinois:nondex-maven-plugin:2.1.1:nondex",
                    "-DnondexSeed=%s" % (row.get("seed") or "933178"),
                    "-DnondexRuns=%s" % (row.get("iterations") or "100"),
                    "-DnondexMode=ONE", "-Dtest=%s" % row["test"]]
            code, out, dur = jd.run_mvn(ctx["flaky_dir"], args, module=ctx["module"],
                                        java=ctx["java"], repo_local=ctx.get("repo_local"))
            obs = jd.make_observation("WARM-ID", {}, code, out, dur,
                                      ctx["flaky_dir"], ctx["module"])
        else:
            obs = g.gate_td_observe(ctx)
            if obs is None:
                return None
    except Exception:
        return None
    return obs.get("failed") or None


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="ds-flash")
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ablation", default=None,
                    help="none|noreflection|space4|nosource|warm")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--max-calls", type=int, default=config.MAX_LLM_CALLS)
    ap.add_argument("--skip-gate", action="store_true",
                    help="run regardless of gate result")
    ap.add_argument("--rows-file", default="",
                    help="run only rows listed in this CSV (e.g. variance subset)")
    args = ap.parse_args()
    ablation = args.ablation if args.ablation and args.ablation != "none" else None
    if ablation == "noreflection":
        max_calls = 2
    else:
        max_calls = args.max_calls
    out_name = "agent_%s" % args.model
    if ablation:
        out_name += "_" + ablation
    if args.seed:
        out_name += "_s%d" % args.seed
    out_path = os.path.join(RESDIR, out_name + ".jsonl")
    os.makedirs(RESDIR, exist_ok=True)
    rows = load_rows(args.only, args.limit, gate_passed_only=not args.skip_gate)
    if args.rows_file:
        with open(args.rows_file, encoding="utf-8") as f:
            keep = {(r["zip"], r["test"]) for r in csv.DictReader(f)}
        rows = [r for r in rows if (r["zip"], r["test"]) in keep]
    log("%s: %d tests -> %s (workers=%d, max_calls=%d)" % (
        out_name, len(rows), out_path, args.workers, max_calls))
    tasks = [(r, args.model, ablation, args.seed, max_calls, out_path, ablation == "warm")
             for r in rows]
    if args.workers <= 1:
        for t in tasks:
            one_test(t)
    else:
        with Pool(args.workers) as p:
            p.map(one_test, tasks)


if __name__ == "__main__":
    main()
