# -*- coding: utf-8 -*-
"""baselines: non-agent baselines over the same 116-test subset, same
8-execution budget (except NaiveRerun=8 runs / SleepScan=8 injections /
SingleShotLLM=1 call + 8 executions of the proposed strategy).

  NaiveRerun    : T1 isolated rerun x8
  RandomStrategy: 8 rounds, uniform random (strategy, params) over the space
  OrderShuffle  : T4 whole-suite random order x8 (fresh seeds)
  SleepScan     : T6 sleep injection, sleeps [100,500,2000,5000]ms x2 = 8
  SingleShotLLM : 1 LLM call proposes ONE strategy, executed 8 times

Writes data/results/<baseline>.jsonl (one JSON per test) + summary CSV.
Usage (inside WSL):
  python3 .../baselines.py [--only ZIP] [--limit N] [--seeds 3] [--baselines a,b]
"""
import csv
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "executor"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
import config
import strategies
import junit_driver as jd
import prepare
import llm_client
import prompts

SUBSET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "subset.csv")
RESDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "results")

BUDGET = 8       # executions per test per baseline run
WALLCLOCK = config.MAX_WALLCLOCK_S


def log(msg):
    print("[base %s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def load_rows(args):
    rows = []
    with open(SUBSET, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    if args.only:
        rows = [r for r in rows if r["zip"] == args.only]
    if args.limit:
        rows = rows[:args.limit]
    rows_file = getattr(args, "rows_file", "")
    if rows_file:
        with open(rows_file, encoding="utf-8") as f:
            keep = {(r["zip"], r["test"]) for r in csv.DictReader(f)}
        rows = [r for r in rows if (r["zip"], r["test"]) in keep]
    if not getattr(args, "skip_gate", False):
        passed = set()
        gate = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data",
                            "gate_results.csv")
        if os.path.exists(gate):
            with open(gate, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    if str(r.get("pass", "")).lower() == "true":
                        passed.add((r["zip"], r["test"]))
        rows = [r for r in rows if (r["zip"], r["test"]) in passed]
    return rows


def get_ctx(row):
    env_path = os.path.join(config.WORKDIR, row["zip"], "build.env")
    if not os.path.exists(env_path):
        info, tail = prepare.prepare(row["zip"], row["module"] or ".", row["java"] or None)
        log("%s build_ok=%s" % (row["zip"], info["build_ok"]))
        if not info["build_ok"]:
            return None
        env_path = os.path.join(config.WORKDIR, row["zip"], "build.env")
    with open(env_path, encoding="utf-8") as f:
        info = json.load(f)
    if not info.get("build_ok"):
        return None
    return {"flaky_dir": info["flaky_dir"], "module": row["module"] or ".",
            "test": row["test"], "java": info["java"],
            "repo_local": info.get("repo_local"), "zip": row["zip"]}


def failed_target(obs, test):
    meth = test.split("#")[-1]
    dotted = test.replace("#", ".")
    for f in obs.get("failed", []):
        name = f.get("name", "")
        if (name == meth or name.endswith("#" + meth) or name.endswith("." + meth)
                or name == test or name == dotted):
            return True
    return False


# ---------------- baseline implementations ----------------

def run_naive(ctx, seed):
    """T1 rerun x8."""
    obs_all = []
    for i in range(BUDGET):
        o = strategies.t1_rerun(ctx, {"repeats": 1})[0]
        o["run"] = i + 1
        obs_all.append(o)
        if failed_target(o, ctx["test"]):
            break
    return obs_all


RANDOM_PARAMS = {
    "T1": lambda rng: {"repeats": rng.choice([1, 1, 2])},
    "T2": lambda rng: {"runs": rng.choice([2, 3])},
    "T3": lambda rng: {"cotests": None},
    "T4": lambda rng: {"seed": rng.randint(1, 99999)},
    "T5": lambda rng: {"polluter": ""},
    "T6": lambda rng: {"sleep_ms": rng.choice([100, 500, 1000, 2000, 5000]),
                       "target_method": ""},
    "T7": lambda rng: {"mode": rng.choice(["cpu", "io"]), "cpus": rng.choice([2, 4])},
    "T8": lambda rng: {"env": rng.choice([{"TZ": "UTC"}, {"TZ": "America/New_York"},
                                          {"LC_ALL": "C"}])},
    "T9": lambda rng: {"xmx": rng.choice(["256m", "512m"]), "fork_count": 0},
    "T10": lambda rng: {"parallel": "classes", "thread_count": rng.choice([2, 4])},
    "T11": lambda rng: {"hosts": []},
    "T12": lambda rng: {"seed": rng.randint(1, 99999), "rounds": rng.choice([50, 100])},
}


def run_random_strategy(ctx, seed):
    rng = random.Random(seed)
    obs_all = []
    cands = strategies.find_candidate_tests(ctx, limit=8)
    used = set()
    for _ in range(BUDGET):
        s = rng.choice(strategies.STRATEGY_IDS)
        p = RANDOM_PARAMS[s](rng)
        if s == "T3":
            p["cotests"] = rng.sample(cands, min(2, len(cands))) if cands else None
        if s == "T5":
            p["polluter"] = rng.choice(cands) if cands else ""
        sig = json.dumps([s, p], sort_keys=True)
        if sig in used:
            continue
        used.add(sig)
        obs = strategies.execute_strategy(ctx, s, p)
        for o in obs:
            obs_all.append(o)
        if any(failed_target(o, ctx["test"]) for o in obs):
            break
    return obs_all


def run_order_shuffle(ctx, seed):
    obs_all = []
    for i in range(BUDGET):
        o = strategies.t4_random_suite(ctx, {"seed": seed * 1000 + i})[0]
        obs_all.append(o)
        if failed_target(o, ctx["test"]):
            break
    return obs_all


def run_sleep_scan(ctx, seed):
    obs_all = []
    sleeps = [100, 500, 2000, 5000]
    for ms in sleeps * 2:
        o = strategies.t6_sleep(ctx, {"sleep_ms": ms, "target_method": ""})[0]
        obs_all.append(o)
        if failed_target(o, ctx["test"]):
            break
    return obs_all


def run_single_shot(ctx, model, seed):
    """One LLM call proposes a strategy; execute it up to BUDGET times."""
    out_path = os.path.join(RESDIR, "singleshot.jsonl")
    result = {"zip": ctx.get("zip"), "test": ctx["test"],
              "model": model, "seed": seed, "reproduced": False,
              "strategy_of_repro": None, "executions": 0, "llm_calls": 1,
              "tokens": {"in": 0, "out": 0}, "history": [], "error": None}
    try:
        content, usage = llm_client.chat(
            model, prompts.build_plan_messages(ctx, [], {"calls": 1, "execs": BUDGET}),
            max_tokens=2000)
        result["tokens"]["in"] += usage.get("prompt_tokens", 0)
        result["tokens"]["out"] += usage.get("completion_tokens", 0)
    except llm_client.LLMError as e:
        result["error"] = str(e)
        return result
    plan = llm_client.extract_json(content)
    strategy = plan.get("strategy", "T1")
    if strategy not in strategies.RUNNERS:
        strategy = "T1"
    from loop import sanitize_params  # reuse the agent's coercion
    params = sanitize_params(strategy, plan.get("params"))
    obs_all = []
    for i in range(BUDGET):
        try:
            obs = strategies.execute_strategy(ctx, strategy, params)
        except Exception as e:
            obs = [{"strategy": strategy, "params": params, "exit_code": -4,
                    "duration_s": 0, "failed": [], "passed": 0,
                    "error": "exc: %s" % e, "log_tail": ""}]
        for o in obs:
            o["hypothesis"] = plan.get("hypothesis", "")
            obs_all.append(o)
        result["executions"] += 1
        if any(failed_target(o, ctx["test"]) for o in obs):
            result["reproduced"] = True
            result["strategy_of_repro"] = strategy
            break
    result["history"] = obs_all
    return result


RUNNERS = {
    "naive": run_naive,
    "random": run_random_strategy,
    "shuffle": run_order_shuffle,
    "sleepscan": run_sleep_scan,
}


def summarize(runs, baseline):
    """Write baseline_results.csv rows for one baseline."""
    rows = []
    for r in runs:
        rows.append({"baseline": baseline, "zip": r["zip"], "test": r["test"],
                     "reproduced": int(bool(r["reproduced"])),
                     "executions": r["executions"], "llm_calls": r.get("llm_calls", 0),
                     "error": r.get("error") or ""})
    return rows


def _map_rows(rows, fn, workers):
    if workers <= 1:
        return [fn(r) for r in rows]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, rows))


def _load_done(path):
    """Set of (zip, test, seed) already persisted in a baseline jsonl (resume)."""
    done = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    done.add((r["zip"], r["test"], r.get("seed", 0)))
                except Exception:
                    continue
    return done


def _run_one_baseline(name, row, seeds, done):
    ctx = get_ctx(row)
    if ctx is None:
        log("%s SKIP (build failed)" % row["zip"])
        return []
    out = []
    for seed in range(seeds):
        if (row["zip"], row["test"], seed) in done:
            continue
        t0 = time.time()
        obs_all = RUNNERS[name](ctx, seed)
        repro = any(failed_target(o, ctx["test"]) for o in obs_all)
        r = {"zip": row["zip"], "test": row["test"], "reproduced": repro,
             "executions": len(obs_all), "llm_calls": 0,
             "history": obs_all, "error": None, "seed": seed}
        log("%s %s#%s seed=%d -> %s (%.0fs)" % (
            name, row["zip"], row["test"].split("#")[-1], seed,
            "REPRO" if repro else "no", time.time() - t0))
        out.append(r)
    return out


def _run_one_singleshot(row, model):
    ctx = get_ctx(row)
    if ctx is None:
        return None
    r = run_single_shot(ctx, model, seed=0)
    log("singleshot %s -> %s" % (row["test"].split("#")[-1],
                                 "REPRO" if r["reproduced"] else "no"))
    return r


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--seeds", type=int, default=1, help="repeat count (variance)")
    ap.add_argument("--baselines", default="naive,random,shuffle,sleepscan")
    ap.add_argument("--model", default="ds-flash")
    ap.add_argument("--with-singleshot", action="store_true")
    ap.add_argument("--skip-gate", action="store_true",
                    help="run on all subset rows regardless of gate result")
    ap.add_argument("--rows-file", default="",
                    help="run only rows listed in this CSV (e.g. variance subset)")
    ap.add_argument("--workers", type=int, default=1,
                    help="parallel workers (one Maven subprocess each); keep <=2 for heat")
    args = ap.parse_args()
    rows = load_rows(args)
    os.makedirs(RESDIR, exist_ok=True)
    summary_csv = os.path.join(RESDIR, "baseline_summary.csv")
    new_file = not os.path.exists(summary_csv)
    with open(summary_csv, "a", newline="", encoding="utf-8") as fsum:
        wsum = csv.DictWriter(fsum, fieldnames=["baseline", "zip", "test", "reproduced",
                                                "executions", "llm_calls", "error"])
        if new_file:
            wsum.writeheader()
        for name in args.baselines.split(","):
            if name not in RUNNERS:
                # singleshot is handled below (--with-singleshot)
                continue
            out_path = os.path.join(RESDIR, "%s.jsonl" % name)
            done = _load_done(out_path)
            with open(out_path, "a", encoding="utf-8") as f:
                if args.workers <= 1:
                    for r in rows:
                        for res in _run_one_baseline(name, r, args.seeds, done):
                            f.write(json.dumps(res, ensure_ascii=False) + "\n")
                            wsum.writerow({"baseline": name, "zip": res["zip"], "test": res["test"],
                                           "reproduced": int(bool(res["reproduced"])),
                                           "executions": res["executions"],
                                           "llm_calls": res.get("llm_calls", 0),
                                           "error": res.get("error") or ""})
                            fsum.flush()
                else:
                    from concurrent.futures import ThreadPoolExecutor, as_completed
                    with ThreadPoolExecutor(max_workers=args.workers) as ex:
                        futs = {ex.submit(_run_one_baseline, name, r, args.seeds, done): r
                                for r in rows}
                        for fut in as_completed(futs):
                            for res in fut.result():
                                f.write(json.dumps(res, ensure_ascii=False) + "\n")
                                wsum.writerow({"baseline": name, "zip": res["zip"], "test": res["test"],
                                               "reproduced": int(bool(res["reproduced"])),
                                               "executions": res["executions"],
                                               "llm_calls": res.get("llm_calls", 0),
                                               "error": res.get("error") or ""})
                                fsum.flush()
        if args.with_singleshot:
            ss_path = os.path.join(RESDIR, "singleshot.jsonl")
            results = _map_rows(rows, lambda r: _run_one_singleshot(r, args.model),
                                args.workers)
            with open(ss_path, "a", encoding="utf-8") as f:
                for r in results:
                    if r is None:
                        continue
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    wsum.writerow({"baseline": "singleshot", "zip": r["zip"], "test": r["test"],
                                   "reproduced": int(bool(r["reproduced"])),
                                   "executions": r["executions"],
                                   "llm_calls": r.get("llm_calls", 0),
                                   "error": r.get("error") or ""})
                    fsum.flush()


if __name__ == "__main__":
    main()
