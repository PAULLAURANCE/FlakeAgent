# -*- coding: utf-8 -*-
"""analyze: compute every paper number from the raw result logs.

Reads:
  data/subset.csv, data/gate_results.csv,
  data/results/agent_*.jsonl, data/results/{naive,random,shuffle,sleepscan,
  singleshot}.jsonl, workdir/<zip>/Fixed.patch
Writes (data/summary/):
  gate_summary.csv, repro_rates.csv, diagnosis.csv, ablation.csv, models.csv,
  cost.csv, atr.csv, heatmap.csv, variance.csv, variance_tests.csv
Run inside WSL: python3 .../analyze.py
"""
import collections
import csv
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
import llm_client  # PRICES single source of truth

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
RESDIR = os.path.join(DATA, "results")
SUMMARY = os.path.join(DATA, "summary")
WORKDIR = "/root/flakeagent/workdir"

CATS = ["od", "td", "nio", "id"]
CAT_PRIORITY = {"td": 0, "id": 1, "nio": 2, "od": 3}


def log(msg):
    print("[analyze] %s" % msg, flush=True)


def load_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def subset_rows(gate_only=True):
    rows = []
    with open(os.path.join(DATA, "subset.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    if gate_only:
        passed = gate_passed()
        rows = [r for r in rows if (r["zip"], r["test"]) in passed]
    return rows


def gate_passed():
    passed = set()
    with open(os.path.join(DATA, "gate_results.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if str(r.get("pass", "")).lower() == "true":
                passed.add((r["zip"], r["test"]))
    return passed


def target_failed(obs, test):
    meth = test.split("#")[-1]
    dotted = test.replace("#", ".")
    for f in obs.get("failed", []):
        name = f.get("name", "")
        if (name == meth or name.endswith("#" + meth) or name.endswith("." + meth)
                or name == test or name == dotted):
            return True
    return False


def rows_by_test(rows):
    return {(r["zip"], r["test"]): r for r in rows}


def first_repro_attempt(result, test):
    """Index of first failing observation in history (1-based), else None."""
    for i, obs in enumerate(result.get("history", [])):
        if target_failed(obs, test):
            return i + 1
    return None


# ---------------- fix-patch parsing ----------------

def _strip_prefix(p):
    """Normalize a patch file path to the repo-relative form (strip Flaky/ or Fixed/)."""
    p = (p or "").replace("\\", "/")
    for pref in ("Flaky/", "Fixed/"):
        if p.startswith(pref):
            return p[len(pref):]
    return p


def parse_fix_patch(zipname):
    """Return {file: {'added': set(lines), 'removed': set(lines)}}.

    Supports both git-style (`diff --git a/x b/x`) and the dataset's
    `diff -ruN Flaky/x Fixed/x` unified-diff format.
    """
    p = os.path.join(WORKDIR, zipname, "Fixed.patch")
    out = {}
    if not os.path.exists(p):
        return out
    cur = None
    try:
        text = open(p, encoding="utf-8", errors="ignore").read()
    except OSError:
        return out
    for line in text.splitlines():
        # git-style file marker: diff --git a/foo b/foo
        if line.startswith("diff --git "):
            m = re.search(r" b/(\S+)", line)
            cur = _strip_prefix(m.group(1)) if m else None
            out.setdefault(cur, {"added": set(), "removed": set()})
            continue
        # dataset-style file marker: +++ Fixed/foo (authoritative new-file path)
        m = re.match(r"^\+\+\+\s+(\S+)", line)
        if m:
            cur = _strip_prefix(m.group(1))
            out.setdefault(cur, {"added": set(), "removed": set(),
                                 "_old": 0, "_new": 0})
            continue
        if line.startswith("---"):
            continue
        if cur is None:
            continue
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if m:
            out[cur]["_old"] = int(m.group(1))
            out[cur]["_new"] = int(m.group(3))
            out[cur]["_n_old"] = int(m.group(2) or 1)
            out[cur]["_n_new"] = int(m.group(4) or 1)
            continue
        if not re.match(r"^[+-]", line):
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            out[cur]["added"].add(out[cur].get("_new", 0))
            out[cur]["_new"] = out[cur].get("_new", 0) + 1
            out[cur]["_n_new"] = out[cur].get("_n_new", 0) - 1
        elif line.startswith("-"):
            out[cur]["removed"].add(out[cur].get("_old", 0))
            out[cur]["_old"] = out[cur].get("_old", 0) + 1
            out[cur]["_n_old"] = out[cur].get("_n_old", 0) - 1
        else:
            out[cur]["_old"] = out[cur].get("_old", 0) + 1
            out[cur]["_new"] = out[cur].get("_new", 0) + 1
    for d in out.values():
        for k in list(d):
            if k.startswith("_"):
                del d[k]
    return out


def match_evidence(evidence, patched):
    """Return (matched_items, total_items) for one evidence list."""
    total = 0
    matched = 0
    for ev in evidence:
        total += 1
        f = (ev.get("file") or "").replace("\\", "/")
        lines = ev.get("lines") or ""
        m = re.match(r"L?(\d+)(?:\s*-\s*L?(\d+))?", lines.strip())
        if not m:
            continue
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        for pf, d in patched.items():
            if f and pf and not (f == pf or f.endswith(pf) or pf.endswith(f)):
                continue
            changed = d["added"] | d["removed"]
            if any(lo <= ln <= hi for ln in changed):
                matched += 1
                break
    return matched, total


# ---------------- file classification ----------------

def result_files():
    files = {}
    for p in glob.glob(os.path.join(RESDIR, "*.jsonl")):
        files[os.path.basename(p)[:-6]] = p
    return files


def method_configs():
    """Return {method_key: {'files': [...], 'kind': 'agent'|'baseline'}}."""
    files = result_files()
    out = {}
    for name in files:
        if name.startswith("agent_"):
            base = name
            parts = name.split("_")
            model = parts[1]
            ablation = None
            seed = 0
            for i, p in enumerate(parts[2:], start=2):
                if p in ("noreflection", "space4", "nosource", "warm"):
                    ablation = p
                elif re.match(r"^s\d+$", p):
                    seed = int(p[1:])
            out.setdefault("agent", []).append((name, model, ablation, seed))
        elif name in ("naive", "random", "shuffle", "sleepscan", "singleshot"):
            out.setdefault("baseline", []).append(name)
    return out


def cost_of(row):
    """USD cost from tokens at list prices (baselines/singleshot have no cost field)."""
    if row.get("cost_usd"):
        return row["cost_usd"]
    tok = row.get("tokens") or {}
    model = row.get("model") or "ds-flash"
    pin, pout = llm_client.PRICES.get(model, llm_client.PRICES["ds-flash"])
    return (tok.get("in", 0) * pin + tok.get("out", 0) * pout) / 1e6


def summarize_repro(rows, subset, key_prefix):
    """Per-category and overall reproduction stats for one method's rows."""
    by_test = rows_by_test(rows)
    stats = {"overall": {"n": 0, "repro": 0}}
    for c in CATS:
        stats[c] = {"n": 0, "repro": 0}
    for r in subset:
        res = by_test.get((r["zip"], r["test"]))
        if res is None:
            continue
        c = r["category"]
        stats[c]["n"] += 1
        stats["overall"]["n"] += 1
        if res.get("reproduced"):
            stats[c]["repro"] += 1
            stats["overall"]["repro"] += 1
    return stats


def main():
    os.makedirs(SUMMARY, exist_ok=True)
    subset = subset_rows(gate_only=True)
    log("gate-passed tests: %d" % len(subset))
    patched_cache = {}
    for r in subset:
        patched_cache[r["zip"]] = parse_fix_patch(r["zip"])

    # ---------- gate summary ----------
    with open(os.path.join(SUMMARY, "gate_summary.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["category", "selected", "projects", "built", "passed", "rate"])
        all_rows = list(csv.DictReader(open(os.path.join(DATA, "subset.csv"), encoding="utf-8")))
        gate_rows = list(csv.DictReader(open(os.path.join(DATA, "gate_results.csv"), encoding="utf-8")))
        for c in CATS:
            sel = [r for r in all_rows if r["category"] == c]
            gr = {(r["zip"], r["test"]): r for r in gate_rows if r["category"] == c}
            built = sum(1 for r in sel if (r["zip"], r["test"]) in gr
                        and gr[(r["zip"], r["test"])]["notes"] != "BUILD_FAILED")
            passed = sum(1 for r in sel if (r["zip"], r["test"]) in gr
                         and str(gr[(r["zip"], r["test"])]["pass"]).lower() == "true")
            w.writerow([c, len(sel), len(set(r["zip"] for r in sel)), built, passed,
                        "%.1f" % (100.0 * passed / built) if built else 0])
        gr_all = {(r["zip"], r["test"]): r for r in gate_rows}
        built_total = sum(1 for r in all_rows if (r["zip"], r["test"]) in gr_all
                          and gr_all[(r["zip"], r["test"])]["notes"] != "BUILD_FAILED")
        w.writerow(["total", len(all_rows), len(set(r["zip"] for r in all_rows)),
                    built_total, len(gate_passed()),
                    "%.1f" % (100.0 * len(gate_passed()) / built_total) if built_total else 0])

    # ---------- reproduction rates ----------
    files = result_files()
    rates = {}
    for name, path in files.items():
        rows = load_jsonl(path)
        if not rows:
            continue
        # baselines with multiple seeds: seed-0 rows for main tables
        if name in ("random", "shuffle"):
            s0 = [r for r in rows if r.get("seed", 0) == 0]
            if s0:
                rows = s0
        if name.startswith("agent_"):
            parts = name.split("_")
            if parts[-1].startswith("s") and parts[-1][1:].isdigit():
                continue  # variance seeds handled separately
        stats = summarize_repro(rows, subset, name)
        rates[name] = stats
    with open(os.path.join(SUMMARY, "repro_rates.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["method"] + [c + "_n" for c in CATS] + [c + "_repro" for c in CATS]
                   + ["overall_n", "overall_repro", "overall_rate"])
        for name, st in sorted(rates.items()):
            w.writerow([name] + [st[c]["n"] for c in CATS] + [st[c]["repro"] for c in CATS]
                       + [st["overall"]["n"], st["overall"]["repro"],
                          "%.1f" % (100.0 * st["overall"]["repro"] / st["overall"]["n"]) if st["overall"]["n"] else 0])
    log("repro_rates written for %d methods" % len(rates))

    # ---------- diagnosis ----------
    diag_rows = []
    for name, path in files.items():
        if not name.startswith("agent_"):
            continue
        for res in load_jsonl(path):
            d = res.get("diagnosis")
            if not d or d.get("error") or not res.get("reproduced"):
                continue
            gt = res.get("category_gt")
            if not gt:
                row = rows_by_test(subset).get((res["zip"], res["test"]))
                gt = row["category"] if row else None
            if not gt:
                continue
            pred = (d.get("category") or "").upper()
            m, t = match_evidence(d.get("evidence") or [], patched_cache.get(res.get("zip"), {}))
            diag_rows.append({
                "method": name, "zip": res.get("zip"), "test": res.get("test"),
                "gt": gt, "pred": pred,
                "cat_correct": 1 if pred == gt.upper() else 0,
                "coarse_correct": 1 if (pred == "OD") == (gt == "od") else 0,
                "ev_matched": m, "ev_total": t,
                "fix_hit": 1 if m > 0 else 0,
                "confidence": d.get("confidence", None),
            })
    with open(os.path.join(SUMMARY, "diagnosis.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["method", "zip", "test", "gt", "pred",
                                          "cat_correct", "coarse_correct", "ev_matched",
                                          "ev_total", "fix_hit", "confidence"])
        w.writeheader()
        w.writerows(diag_rows)
    log("diagnosis rows: %d" % len(diag_rows))

    # ---------- heatmap ----------
    heat = collections.defaultdict(int)
    agent_main = [p for n, p in files.items()
                  if n.startswith("agent_") and n == "agent_ds-flash"]
    for path in agent_main:
        for res in load_jsonl(path):
            if not res.get("reproduced"):
                continue
            heat[(res.get("category_gt"), res.get("strategy_of_repro"))] += 1
    with open(os.path.join(SUMMARY, "heatmap.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["category", "strategy", "count"])
        for (c, s), n in sorted(heat.items()):
            w.writerow([c, s, n])
    log("heatmap written: %d cells" % len(heat))

    # ---------- ATR ----------
    with open(os.path.join(SUMMARY, "atr.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["method", "zip", "test", "attempts", "reproduced"])
        for name, path in files.items():
            for res in load_jsonl(path):
                if res.get("reproduced"):
                    at = first_repro_attempt(res, res.get("test", ""))
                    if at:
                        w.writerow([name, res.get("zip"), res.get("test"), at, 1])
    log("atr written")

    # ---------- cost ----------
    cost_rows = []
    for name, path in files.items():
        for res in load_jsonl(path):
            if res.get("error") and not res.get("reproduced"):
                continue
            cost_rows.append({
                "method": name,
                "llm_calls": res.get("llm_calls", 0),
                "executions": res.get("executions", 0),
                "tokens_in": (res.get("tokens") or {}).get("in", 0),
                "tokens_out": (res.get("tokens") or {}).get("out", 0),
                "cost_usd": cost_of(res),
                "wallclock_s": res.get("wallclock_s") or sum(
                    o.get("duration_s", 0) for o in res.get("history", [])),
            })
    with open(os.path.join(SUMMARY, "cost.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["method", "llm_calls", "executions",
                                          "tokens_in", "tokens_out", "cost_usd", "wallclock_s"])
        w.writeheader()
        w.writerows(cost_rows)
    log("cost rows: %d" % len(cost_rows))

    # ---------- variance (stratified 30-test subset, seed 42) ----------
    import random
    rng = random.Random(42)
    by_cat = collections.defaultdict(list)
    for r in subset:
        by_cat[r["category"]].append(r)
    var_rows = []
    for c in CATS:
        pool = sorted(by_cat[c], key=lambda r: (r["zip"], r["test"]))
        n = max(1, round(len(pool) * 30.0 / max(1, len(subset))))
        var_rows.extend(rng.sample(pool, min(n, len(pool))))
    var_rows = var_rows[:30]
    with open(os.path.join(SUMMARY, "variance_tests.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(subset[0].keys()))
        w.writeheader()
        w.writerows(var_rows)
    var_keys = {(r["zip"], r["test"]) for r in var_rows}
    with open(os.path.join(SUMMARY, "variance.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["method", "seeds", "mean_rate", "std_rate", "n"])
        for name, path in files.items():
            if re.match(r"^agent_\w+(_s\d+)?$", name):
                base = name.split("_s")[0] if "_s" in name and name.split("_s")[-1].isdigit() else name
                seeds = sorted(n for n in files
                               if re.match(r"^%s(_s\d+)?$" % re.escape(base), n))
                rates = []
                n_tests = 0
                for sn in seeds:
                    rows = [r for r in load_jsonl(files[sn]) if (r["zip"], r["test"]) in var_keys]
                    if not rows:
                        continue
                    n_tests = len(rows)
                    rates.append(100.0 * sum(1 for r in rows if r.get("reproduced")) / len(rows))
                if len(rates) >= 2:
                    mean = sum(rates) / len(rates)
                    std = (sum((x - mean) ** 2 for x in rates) / len(rates)) ** 0.5
                    w.writerow([base, len(rates), "%.1f" % mean, "%.1f" % std, n_tests])
        for bname in ("random", "shuffle", "naive"):
            if bname not in files:
                continue
            rows = [r for r in load_jsonl(files[bname]) if (r["zip"], r["test"]) in var_keys]
            by_seed = collections.defaultdict(list)
            for r in rows:
                by_seed[r.get("seed", 0)].append(r)
            rates = [100.0 * sum(1 for r in rs if r.get("reproduced")) / len(rs)
                     for rs in by_seed.values() if rs]
            if rates:
                mean = sum(rates) / len(rates)
                std = (sum((x - mean) ** 2 for x in rates) / len(rates)) ** 0.5
                w.writerow([bname, len(rates), "%.1f" % mean, "%.1f" % std, len(by_seed[0])])
    log("variance written: %d tests" % len(var_rows))

    log("ALL DONE")


if __name__ == "__main__":
    main()
