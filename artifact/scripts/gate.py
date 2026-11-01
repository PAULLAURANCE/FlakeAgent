# -*- coding: utf-8 -*-
"""gate: validation gate for the 116-test subset.

For each test, run its category's OFFICIAL ReproFlake mechanism up to
GATE_RUNS times (early stop on first reproduced failure):
  TD  : mvn -pl M test -Dtest=T        (isolated rerun)
  OD  : mvn -pl M test -Dsurefire.runOrder=testorder -Dtest="P,V"
  NIO : mvn testrunner:testplugin + .dtfixingtools/original-order (same-JVM x2)
  ID  : nondex-maven-plugin nondexSeed/seed, nondexRuns=iterations, mode ONE

Writes data/gate_results.csv incrementally (one row per test).
Usage (inside WSL):
  python3 /mnt/c/.../artifact/scripts/gate.py [--only ZIP] [--limit N]
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "executor"))
import config
import junit_driver as jd
import patcher
import prepare
import strategies

SUBSET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "subset.csv")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "gate_results.csv")

GATE_RUNS = {"td": 40, "od": 10, "nio": 10, "id": 10}  # max mechanism invocations per test
BUDGET_S = {"td": 2400, "od": 1500, "nio": 1500, "id": 1500}  # per-test wallclock budget

# rescue-pass overrides (env): GATE_RESCUE_RUNS_TD=100 GATE_RESCUE_BUDGET_TD=6000
if os.environ.get("GATE_RESCUE_RUNS_TD"):
    GATE_RUNS["td"] = int(os.environ["GATE_RESCUE_RUNS_TD"])
if os.environ.get("GATE_RESCUE_BUDGET_TD"):
    BUDGET_S["td"] = int(os.environ["GATE_RESCUE_BUDGET_TD"])


def log(msg):
    print("[gate %s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def load_subset():
    rows = []
    with open(SUBSET, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def target_failed(obs, test):
    meth = test.split("#")[-1]
    dotted = test.replace("#", ".")
    for f in obs.get("failed", []):
        name = f.get("name", "")
        if (name == meth or name.endswith("#" + meth) or name.endswith("." + meth)
                or name == test or name == dotted):
            return True
    return False


def _orig_files(ctx):
    """Set of *.orig backup files under the Flaky tree."""
    out = set()
    for dp, _, fns in os.walk(ctx["flaky_dir"]):
        for fn in fns:
            if fn.endswith(".orig"):
                out.add(os.path.join(dp, fn))
    return out


def _apply_flaky_change(ctx):
    """Apply the dataset's FlakyCodeChange.patch (the TD sleep injection).

    Runs `patch -p1 -b` from the Flaky dir; returns the newly created .orig
    backup paths (None if the zip has no injection patch).
    """
    ziproot = os.path.dirname(ctx["flaky_dir"])  # flaky_dir = <ziproot>/Flaky
    patch_path = os.path.join(ziproot, "FlakyCodeChange.patch")
    if not os.path.exists(patch_path):
        return None
    # restore any .orig leftovers from a crashed earlier run before re-applying
    stale = _orig_files(ctx)
    if stale:
        _revert_flaky_change(stale)
    try:
        with open(patch_path, "rb") as pf:
            subprocess.run(["patch", "-N", "-p1", "-b"], cwd=ctx["flaky_dir"],
                           stdin=pf, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=60)
    except Exception as e:
        print("[gate] patch apply exc: %s" % e, flush=True)
        return None
    return sorted(_orig_files(ctx)) or None


def _revert_flaky_change(orig_files):
    if not orig_files:
        return
    future = time.time() + 10
    for o in orig_files:
        try:
            os.replace(o, o[:-5])  # strip .orig
            # Force Maven's incremental compiler to recompile the reverted
            # source (its stale injected .class in target/ otherwise survives
            # and causes spurious failures on the agent's later `mvn test`).
            os.utime(o[:-5], (future, future))
        except OSError:
            pass


def _gate_td_rerun(ctx, budget_end):
    """Fallback: isolated rerun xN (used when no injection patch exists)."""
    n_fail = 0
    n = 0
    while n < ctx.get("gate_runs", 10) and time.time() < budget_end:
        n += 1
        try:
            obs = jd.run_test(ctx["flaky_dir"], ctx["module"], ctx["test"],
                              strategy="GATE-TD", params={"run": n}, java=ctx["java"],
                              repo_local=ctx.get("repo_local"))
        except Exception as e:
            import traceback
            print("[gate %s] td run %d exc: %s\n%s" % (
                time.strftime("%H:%M:%S"), n, e, traceback.format_exc()[-1500:]), flush=True)
            continue
        if obs.get("failed"):
            n_fail += 1
            return {"n_runs": n, "fails": n_fail, "pass": True, "notes": ""}
    return {"n_runs": n, "fails": n_fail, "pass": False,
            "notes": "timeout" if time.time() >= budget_end else ""}


def gate_td(ctx, budget_end):
    """TD official mechanism: apply the dataset's sleep-injection patch
    (FlakyCodeChange.patch) and run the test until it fails."""
    orig = _apply_flaky_change(ctx)
    if orig is None:
        return _gate_td_rerun(ctx, budget_end)
    try:
        # a patch under src/main (dependency-module code) needs a rebuild so the
        # test run picks up the recompiled class; test-file patches are
        # auto-compiled by `mvn test`.
        if any("/src/main/" in o.replace("\\", "/") for o in orig):
            ok, tail = patcher.rebuild(ctx, m2=ctx.get("repo_local"))
            if not ok:
                ok, tail = patcher.rebuild(ctx, offline=False, m2=ctx.get("repo_local"))
            if not ok:
                return {"n_runs": 0, "fails": 0, "pass": False,
                        "notes": "BUILD_FAILED(patch)"}
        n = 0
        while n < 3 and time.time() < budget_end:
            n += 1
            try:
                obs = jd.run_test(ctx["flaky_dir"], ctx["module"], ctx["test"],
                                  strategy="GATE-TD", params={"run": n}, java=ctx["java"],
                                  repo_local=ctx.get("repo_local"))
            except Exception:
                continue
            if target_failed(obs, ctx["test"]):
                return {"n_runs": n, "fails": 1, "pass": True, "notes": "sleep-inject"}
        return {"n_runs": n, "fails": 0, "pass": False,
                "notes": "timeout" if time.time() >= budget_end else "no-fail-after-inject"}
    finally:
        _revert_flaky_change(orig)


def gate_od(ctx, polluter, budget_end):
    n_fail = 0
    n = 0
    spec = "%s,%s" % (polluter, ctx["test"]) if polluter else ctx["test"]
    while n < ctx.get("gate_runs", 10) and time.time() < budget_end:
        n += 1
        try:
            obs = jd.run_ordered(ctx["flaky_dir"], ctx["module"], spec,
                                 strategy="GATE-OD", params={"run": n}, java=ctx["java"],
                                 repo_local=ctx.get("repo_local"))
        except Exception as e:
            return {"n_runs": n, "fails": n_fail, "pass": False, "notes": "exc %s" % e}
        if obs.get("error") and "could not be resolved" in (obs.get("log_tail") or ""):
            # custom surefire missing from this zip's cache: fall back to the
            # testrunner same-JVM order execution (iDFlakies substrate)
            obs = strategies.run_testplugin_order(ctx["flaky_dir"], ctx["module"],
                                                  spec.split(","), strategy="GATE-OD-TR",
                                                  params={"run": n}, java=ctx["java"],
                                                  repo_local=ctx.get("repo_local"))
        if target_failed(obs, ctx["test"]):
            n_fail += 1
            return {"n_runs": n, "fails": n_fail, "pass": True, "notes": ""}
    return {"n_runs": n, "fails": n_fail, "pass": False,
            "notes": "timeout" if time.time() >= budget_end else ""}


def _nio_iteration(ctx):
    """One testplugin invocation; returns (ok_run, flaky, obs)."""
    import strategies  # reuse T2 executor
    obs_list = strategies.t2_double(ctx, {"runs": 2})
    obs = obs_list[0]
    if obs.get("error") and obs.get("exit_code", 0) not in (0, 1):
        return False, False, obs
    subs = obs.get("subruns") or []
    results = [s.get("result", "").upper() for s in subs]
    flaky = ("PASS" in results or "SUCCESS" in results) and any(
        r in ("ERROR", "FAILURE", "FAIL") for r in results)
    return True, flaky, obs


def gate_nio(ctx, budget_end):
    n = 0
    while n < ctx.get("gate_runs", 10) and time.time() < budget_end:
        n += 1
        try:
            ok, flaky, obs = _nio_iteration(ctx)
        except Exception as e:
            return {"n_runs": n, "fails": 0, "pass": False, "notes": "exc %s" % e}
        if flaky and target_failed(obs, ctx["test"]):
            return {"n_runs": n, "fails": 1, "pass": True, "notes": ""}
    return {"n_runs": n, "fails": 0, "pass": False,
            "notes": "timeout" if time.time() >= budget_end else ""}


def gate_id(ctx, seed, rounds, budget_end):
    args = ["-pl", ctx["module"],
            "edu.illinois:nondex-maven-plugin:2.1.1:nondex",
            "-DnondexSeed=%s" % (seed or "933178"),
            "-DnondexRuns=%s" % (rounds or "100"),
            "-DnondexMode=ONE",
            "-Dtest=%s" % ctx["test"]]
    try:
        code, out, dur = jd.run_mvn(ctx["flaky_dir"], args, module=ctx["module"],
                                    java=ctx["java"],
                                    timeout_s=max(config.RUN_TIMEOUT_S * 3,
                                                  int(BUDGET_S["id"] * 0.8)),
                                    repo_local=ctx.get("repo_local"))
    except Exception as e:
        return {"n_runs": 1, "fails": 0, "pass": False, "notes": "exc %s" % e}
    obs = jd.make_observation("GATE-ID", {"seed": seed, "rounds": rounds},
                              code, out, dur, ctx["flaky_dir"], ctx["module"])
    fails = len(obs.get("failed") or [])
    return {"n_runs": 1, "fails": fails, "pass": fails > 0, "notes": ""}


def gate_td_observe(ctx):
    """Apply the TD sleep-injection patch and run once; return the observation
    (or None). Reverts the patch. Used by the Warm ablation to seed a failure."""
    orig = _apply_flaky_change(ctx)
    if orig is None:
        return None
    try:
        if any("/src/main/" in o.replace("\\", "/") for o in orig):
            ok, tail = patcher.rebuild(ctx, m2=ctx.get("repo_local"))
            if not ok:
                ok, tail = patcher.rebuild(ctx, offline=False, m2=ctx.get("repo_local"))
            if not ok:
                return None
        return jd.run_test(ctx["flaky_dir"], ctx["module"], ctx["test"],
                           strategy="WARM-TD", params={}, java=ctx["java"],
                           repo_local=ctx.get("repo_local"))
    except Exception:
        return None
    finally:
        _revert_flaky_change(orig)


GATES = {"td": gate_td, "od": gate_od, "nio": gate_nio, "id": gate_id}


def run_one(row):
    """Prepare zip once (cache build.env), run the gate for one test."""
    zipname = row["zip"]
    module = row["module"] or "."
    java = row["java"] or None
    env_path = os.path.join(config.WORKDIR, zipname, "build.env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            info = json.load(f)
        if not info["build_ok"] and not info.get("build_retried"):
            # the cached failure predates the executor fixes (stdin/TERM/jline);
            # retry the build once per zip before declaring rows unbuildable
            log("%s: cached build_ok=False -> rebuilding once" % zipname)
            info, tail = prepare.prepare(zipname, module, java)
            info["build_retried"] = True
            try:
                with open(env_path, "w", encoding="utf-8") as f:
                    json.dump(info, f)
            except OSError:
                pass
            log("%s: rebuild retry build_ok=%s | %s" % (zipname, info["build_ok"],
                                                       tail.splitlines()[-1] if tail else ""))
        else:
            log("%s: using cached build.env (build_ok=%s)" % (zipname, info["build_ok"]))
    else:
        info, tail = prepare.prepare(zipname, module, java)
        log("%s: prepare build_ok=%s | %s" % (zipname, info["build_ok"], tail.splitlines()[-1] if tail else ""))
    if not info["build_ok"]:
        return {"category": row["category"], "test": row["test"], "zip": zipname,
                "module": module, "n_runs": 0, "fails": 0, "pass": False,
                "notes": "BUILD_FAILED"}
    ctx = {"flaky_dir": info["flaky_dir"], "module": module, "test": row["test"],
           "java": info["java"], "repo_local": info.get("repo_local"), "zip": zipname,
           "gate_runs": GATE_RUNS.get(row["category"], 10)}
    cat = row["category"]
    budget_end = time.time() + BUDGET_S.get(cat, 1500)
    try:
        if cat == "od":
            res = gate_od(ctx, row.get("polluter") or "", budget_end)
        elif cat == "nio":
            res = gate_nio(ctx, budget_end)
        elif cat == "id":
            res = gate_id(ctx, row.get("seed"), row.get("iterations"), budget_end)
        else:
            res = gate_td(ctx, budget_end)
    except Exception as e:
        res = {"n_runs": 0, "fails": 0, "pass": False, "notes": "gate exc: %s" % e}
    out = {"category": row["category"], "test": row["test"], "zip": zipname,
           "module": module}
    out.update(res)
    log("%s %s -> %s (%s)" % (cat, row["test"].split("#")[-1],
                              "PASS" if out["pass"] else "FAIL", out["notes"] or "n=%d" % out["n_runs"]))
    return out


def main():
    import argparse
    import threading
    from concurrent.futures import ThreadPoolExecutor
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true", help="re-run tests already in gate_results.csv")
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()
    rows = load_subset()
    if args.only:
        rows = [r for r in rows if r["zip"] == args.only]
    if args.limit:
        rows = rows[:args.limit]
    # cheap mechanisms first (TD/ID/NIO), then OD
    rows.sort(key=lambda r: {"td": 0, "id": 1, "nio": 2, "od": 3}.get(r["category"], 4))

    done = set()
    if os.path.exists(OUT) and not args.force:
        with open(OUT, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                done.add((r["zip"], r["test"]))
    rows = [r for r in rows if (r["zip"], r["test"]) not in done]

    fieldnames = ["category", "test", "zip", "module", "n_runs", "fails", "pass", "notes"]
    if not os.path.exists(OUT):
        with open(OUT, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fieldnames).writeheader()
    lock = threading.Lock()

    def worker(r):
        res = run_one(r)
        with lock:
            with open(OUT, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writerow({k: res.get(k, "") for k in fieldnames})
                f.flush()

    # zip affinity: all rows of one zip go to the same worker (avoids concurrent
    # prepare of the same project snapshot)
    by_worker = [[] for _ in range(max(1, args.workers))]
    for r in rows:
        by_worker[hash(r["zip"]) % len(by_worker)].append(r)
    log("dispatching %d rows across %d workers" % (len(rows), len(by_worker)))
    with ThreadPoolExecutor(max_workers=len(by_worker)) as ex:
        futs = [ex.submit(worker, r) for wl in by_worker for r in wl]
        for fut in futs:
            fut.result()


if __name__ == "__main__":
    main()
