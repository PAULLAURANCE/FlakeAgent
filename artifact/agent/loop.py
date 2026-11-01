# -*- coding: utf-8 -*-
"""loop: the bounded FlakeAgent loop.

    step 0 : 3 baseline isolated reruns (no LLM)
    rounds : <=5 LLM plan calls, <=8 executions, <=45 min wall clock
    on failure: 1 LLM diagnose call -> {category, root_cause, evidence[], confidence}

Writes one JSON line per test run to the results file.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "executor"))
import config
import strategies
import llm_client
import prompts

def target_failed(obs, test):
    """Did the target test fail in this observation?"""
    meth = test.split("#")[-1]
    dotted = test.replace("#", ".")
    for f in obs.get("failed", []):
        name = f.get("name", "")
        if (name == meth or name.endswith("#" + meth) or name.endswith("." + meth)
                or name == test or name == dotted
                or name.endswith(test) or name.endswith(dotted)):
            return True
    return False


def sanitize_params(strategy, params):
    """Coerce LLM params to sane types/ranges (anti-shoot-in-foot)."""
    p = params if isinstance(params, dict) else {}
    out = {}
    try:
        if strategy == "T1":
            out["repeats"] = max(1, min(int(p.get("repeats", 1)), 3))
        elif strategy == "T2":
            out["runs"] = max(2, min(int(p.get("runs", 2)), 4))
        elif strategy == "T3":
            cotests = p.get("cotests")
            out["cotests"] = cotests[:4] if isinstance(cotests, list) else None
        elif strategy == "T4":
            out["seed"] = int(p.get("seed", time.time() % 100000)) % 100000
        elif strategy == "T5":
            out["polluter"] = str(p.get("polluter", ""))[:200]
        elif strategy == "T6":
            out["sleep_ms"] = max(10, min(int(p.get("sleep_ms", 500)), 20000))
            out["target_method"] = str(p.get("target_method", ""))[:120]
        elif strategy == "T7":
            out["mode"] = p.get("mode", "cpu") if p.get("mode") in ("cpu", "io", "cpu-io") else "cpu"
            out["cpus"] = max(1, min(int(p.get("cpus", 2)), 6))
        elif strategy == "T8":
            env = p.get("env")
            out["env"] = env if isinstance(env, dict) else {}
        elif strategy == "T9":
            out["xmx"] = str(p.get("xmx", "256m"))[:10]
            out["fork_count"] = int(p.get("fork_count", 0))
        elif strategy == "T10":
            out["parallel"] = p.get("parallel", "classes") if p.get("parallel") in ("classes", "methods") else "classes"
            out["thread_count"] = max(1, min(int(p.get("thread_count", 4)), 8))
        elif strategy == "T11":
            hosts = p.get("hosts")
            out["hosts"] = [str(h)[:100] for h in hosts[:5]] if isinstance(hosts, list) else []
        elif strategy == "T12":
            out["seed"] = int(p.get("seed", 933178))
            out["rounds"] = max(10, min(int(p.get("rounds", 100)), 100))
    except (TypeError, ValueError):
        out = {}
    return out


def run_agent(ctx, model_key, out_path, ablation=None, warm_failure=None,
              seed=0, max_calls=config.MAX_LLM_CALLS,
              max_execs=config.MAX_EXECUTIONS, wallclock=config.MAX_WALLCLOCK_S):
    """Run the full agent on one test. Returns the result dict (also appended to out_path)."""
    import random
    random.seed(seed)
    t0 = time.time()
    result = {
        "zip": ctx.get("zip"), "test": ctx["test"], "category_gt": ctx.get("category_gt"),
        "model": model_key, "ablation": ablation, "seed": seed,
        "reproduced": False, "strategy_of_repro": None, "executions": 0,
        "llm_calls": 0, "history": [], "diagnosis": None,
        "wallclock_s": 0, "tokens": {"in": 0, "out": 0},
        "cost_usd": 0.0, "cost_billed_usd": 0.0, "error": None,
        "forced_switches": 0,
    }
    history = []           # observation dicts, most recent last
    executions = 0
    calls = 0
    used_plans = set()
    plan_strats = []       # planned strategy per round (anti-degeneracy)

    def log_usage(usage):
        result["tokens"]["in"] += usage.get("prompt_tokens", 0)
        result["tokens"]["out"] += usage.get("completion_tokens", 0)
        pin, pout = llm_client.PRICES.get(model_key, (0, 0))
        result["cost_usd"] += (usage.get("prompt_tokens", 0) * pin
                               + usage.get("completion_tokens", 0) * pout) / 1e6
        ticks = usage.get("cost_in_usd_ticks")
        if ticks is not None:
            # relay-reported billed cost (grok); 1 tick = 1e-8 USD convention
            result["cost_billed_usd"] += ticks * 1e-8

    def call_llm(messages):
        """chat() with one retry on empty content (reasoning models can burn
        the whole output budget on hidden reasoning)."""
        content, usage = llm_client.chat(model_key, messages, max_tokens=2000)
        if not content.strip():
            content, usage = llm_client.chat(model_key, messages, max_tokens=2000)
        return content, usage

    # ---- step 0: baseline reruns (no LLM) ----
    if not warm_failure:
        for i in range(config.BASELINE_RUNS):
            try:
                obs_list = strategies.execute_strategy(ctx, "T1", {"repeats": 1, "baseline": i + 1})
            except Exception as e:
                obs_list = [{"strategy": "T1", "params": {"repeats": 1}, "exit_code": -4,
                             "duration_s": 0, "failed": [], "passed": 0,
                             "error": "executor exception: %s" % e, "log_tail": ""}]
            history.extend(obs_list)
            executions += sum(max(1, o.get("params", {}).get("repeats", 1)) for o in obs_list)
            for o in obs_list:
                if target_failed(o, ctx["test"]):
                    result["reproduced"] = True
                    result["strategy_of_repro"] = "T1"
                    break
            if result["reproduced"]:
                break
    else:
        history.append({"strategy": "WARM", "params": {"given": True}, "exit_code": 0,
                        "duration_s": 0, "failed": warm_failure, "passed": 0, "error": None,
                        "log_tail": ""})
        if warm_failure:  # failure already observed -> skip reproduction, diagnose directly
            result["reproduced"] = True
            result["strategy_of_repro"] = "WARM"

    # ---- agent rounds ----
    if ablation == "space4":
        strategies.VALID_STRATEGIES = {"T1", "T2", "T5", "T6"}
    else:
        strategies.VALID_STRATEGIES = set(strategies.STRATEGY_IDS)
    include_source = ablation != "nosource"
    while (not result["reproduced"] and calls < max_calls and executions < max_execs
           and time.time() - t0 < wallclock):
        budget = {"calls": max_calls - calls, "execs": max_execs - executions}
        # -reflection ablation: the agent plans blind, without observation history
        hist_view = [] if ablation == "noreflection" else history
        try:
            content, usage = call_llm(prompts.build_plan_messages(
                ctx, hist_view, budget, include_source=include_source))
            log_usage(usage)
            calls += 1
        except llm_client.LLMError as e:
            result["error"] = str(e)
            break
        plan = llm_client.extract_json(content)
        strategy = plan.get("strategy", "")
        if strategy not in strategies.VALID_STRATEGIES:
            strategy = "T1"
        params = sanitize_params(strategy, plan.get("params"))
        sig = json.dumps([strategy, params], sort_keys=True)
        if sig in used_plans:
            # anti-degeneracy: force a different family
            strategy = strategies.family_switch(strategy, strategies.VALID_STRATEGIES)
            params = sanitize_params(strategy, {})
            sig = json.dumps([strategy, params], sort_keys=True)
            result["forced_switches"] += 1
        # anti-degeneracy: same strategy planned twice in a row (e.g. T4 with
        # new seeds) -> force a different family
        if len(plan_strats) >= 2 and plan_strats[-1] == strategy and plan_strats[-2] == strategy:
            strategy = strategies.family_switch(strategy, strategies.VALID_STRATEGIES)
            params = sanitize_params(strategy, {})
            sig = json.dumps([strategy, params], sort_keys=True)
            result["forced_switches"] += 1
        plan_strats.append(strategy)
        used_plans.add(sig)
        try:
            obs_list = strategies.execute_strategy(ctx, strategy, params)
        except Exception as e:
            obs_list = [{"strategy": strategy, "params": params, "exit_code": -4,
                         "duration_s": 0, "failed": [], "passed": 0,
                         "error": "executor exception: %s" % e, "log_tail": ""}]
        for o in obs_list:
            o["hypothesis"] = plan.get("hypothesis", "")
        history.extend(obs_list)
        executions += 1
        if executions > max_execs:
            history = history[-8:]
        for o in obs_list:
            if target_failed(o, ctx["test"]):
                result["reproduced"] = True
                result["strategy_of_repro"] = o["strategy"]
                break
        history = history[-8:]  # bounded context

    # ---- diagnose on success ----
    if result["reproduced"]:
        failure = next((o for o in reversed(history) if target_failed(o, ctx["test"])), None)
        try:
            content, usage = call_llm(prompts.build_diagnose_messages(ctx, history, failure or {}))
            log_usage(usage)
            calls += 1
            diag = llm_client.extract_json(content)
            diag["raw"] = content[:2000]
            result["diagnosis"] = diag
        except llm_client.LLMError as e:
            result["diagnosis"] = {"error": str(e)}

    result["history"] = history
    result["executions"] = executions
    result["llm_calls"] = calls
    result["wallclock_s"] = round(time.time() - t0, 1)
    with open(out_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="flaky dir (WSL path)")
    ap.add_argument("--module", default=".")
    ap.add_argument("--test", required=True)
    ap.add_argument("--java", default="11")
    ap.add_argument("--model", default="ds-flash")
    ap.add_argument("--out", required=True)
    ap.add_argument("--zip", default="")
    ap.add_argument("--category-gt", default="")
    ap.add_argument("--ablation", default=None)
    args = ap.parse_args()
    ctx = {"flaky_dir": args.project, "module": args.module, "test": args.test,
           "java": args.java, "zip": args.zip, "category_gt": args.category_gt}
    r = run_agent(ctx, args.model, args.out, ablation=args.ablation)
    print(json.dumps({k: r[k] for k in
                      ["test", "reproduced", "strategy_of_repro", "executions",
                       "llm_calls", "wallclock_s", "tokens", "error"]},
                     indent=2, ensure_ascii=False))
