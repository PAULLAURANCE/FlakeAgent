# -*- coding: utf-8 -*-
"""prompts: system / plan / diagnose prompt assembly for FlakeAgent."""

SYSTEM = """You are FlakeAgent, an autonomous debugging agent that reproduces flaky test failures in real Java/Maven projects and then diagnoses their root cause.

A flaky test is a test that passes and fails non-deterministically on the same code. You are given a test identifier and read-only access to the project source. You must figure out WHY the test can fail and which concrete strategy is most likely to MAKE it fail now.

You act in rounds. In each round you:
1. form a causal hypothesis about the flakiness mechanism;
2. choose exactly ONE strategy from the tool set and its parameters;
3. the harness executes it locally and reports the outcome.

You must output a single JSON object. No markdown fences, no prose outside the JSON."""

PLAN_SCHEMA = """Output exactly this JSON object:
{
  "hypothesis": "one sentence: what mechanism makes this test flaky and why your strategy will trigger it",
  "strategy": "<one of T1..T12>",
  "params": { ... strategy-specific parameters, see below ... },
  "expected": "what observation would confirm the hypothesis"
}

Strategy parameter guide (executor-side mechanics):
- T1 rerun-isolated: params {"repeats": 1..3}. Plain rerun of the test in a fresh JVM.
- T2 same-JVM-double: params {"runs": 2..4}. Runs the test back-to-back in the SAME JVM (exposes non-idempotent tests / leaked static state).
- T3 order-permutation: params {"cotests": ["pkg.OtherTest", ...]}. Runs the test with chosen co-tests in the same JVM, in that order.
- T4 random-suite-order: params {"seed": <int>}. Runs the whole module test suite in a random order.
- T5 polluter-victim: params {"polluter": "pkg.PolluterTest" or "pkg.PolluterTest#method"}. Runs the polluter BEFORE the flaky test in the same JVM (exposes order-dependent tests; a sibling test method of the same class is a valid polluter).
- T6 sleep-injection: params {"sleep_ms": 100..20000, "target_method": "<method name>"}. Injects Thread.sleep at the start of the chosen method, recompiles, runs the test, then reverts.
- T7 system-stress: params {"mode": "cpu"|"io"|"cpu-io", "cpus": 1..6}. Runs the test under CPU/IO load.
- T8 env-manipulation: params {"env": {"TZ": "...", "LANG": "...", "LC_ALL": "...", "MALLOC_ARENA_MAX": "..."}}. Runs the test with extra environment variables.
- T9 resource-limit: params {"xmx": "128m..1g", "fork_count": 0|1}. Runs the test with a small heap and no forking.
- T10 parallel-execution: params {"parallel": "classes"|"methods", "thread_count": 2..8}. Runs the test class with parallel execution.
- T11 external-block: params {"hosts": ["host.name", ...]}. Blocks network access to the listed hosts via /etc/hosts during the run.
- T12 nondex-seed: params {"seed": <int>, "rounds": 10..100}. Perturbs JDK nondeterminism (hash order etc.) with the NonDex tool.

Rules (hard constraints, enforced by the harness):
- You may not repeat the same strategy with identical parameters twice.
- If the last two observations were both failures/passes with no new information, switch strategy FAMILY (order-dependent vs timing vs nondeterminism).
- Prefer cheap and safe strategies first; escalate only when observations suggest a mechanism."""

DIAGNOSE_TASK = """A failure has now been reproduced for the flaky test. Diagnose the root cause using the observations collected plus the source code.

Output exactly this JSON object:
{
  "category": "OD" | "TD" | "NIO" | "ID" | "UNKNOWN",
  "root_cause": "2-3 sentences naming the mechanism: which state/order/timing/nondeterminism causes the failure",
  "evidence": [
    {"file": "path relative to project root", "lines": "L10-L15", "snippet": "<the code lines>", "why": "how these lines cause the observed failure"}
  ],
  "confidence": 0.0 to 1.0
}
Category definitions:
- OD (order-dependent): the test fails only when another test runs before it in the same JVM (shared state).
- TD (time-dependent): the test fails when timing/load changes (races, deadlines, sleeps, timeouts).
- NIO (non-idempotent-outcome): the test fails on its second execution in the same JVM because code/environment was mutated.
- ID (implementation-dependent): the test depends on nondeterministic implementation behavior (hash order, random seeds, reflection, sets/maps iteration).
Cite evidence as specific file lines you actually observed in the source or failure stack. If the failure stack points to a file, cite that file and line. Do not invent lines."""


def read_file(path, max_lines=220):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError:
        return ""
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["... (%d more lines truncated)" % (len(lines) - max_lines)]
    return "".join(lines)


def test_source_context(ctx, max_files=2):
    """Excerpt the test class file (+ one file named in the failure stack)."""
    flaky = ctx["flaky_dir"]
    module = ctx["module"]
    parts = []
    cls_path = ctx["test"].split("#")[0]
    rel = cls_path.replace(".", "/") + ".java"
    cands = []
    base = os.path.join(flaky, module) if module != "." else flaky
    for srcroot in [os.path.join(base, "src", "test", "java"),
                    os.path.join(flaky, "src", "test", "java")]:
        p = os.path.join(srcroot, rel)
        if os.path.exists(p):
            cands.append(p)
    for p in cands[:max_files]:
        parts.append("=== TEST SOURCE %s ===\n%s" % (os.path.relpath(p, flaky), read_file(p)))
    return "\n".join(parts)


import os  # noqa: E402


def obs_summary(obs):
    if not obs:
        return "no runs yet"
    lines = []
    for o in obs:
        status = "FAIL" if o.get("failed") else ("ERR" if o.get("error") else "PASS")
        detail = ""
        if o.get("failed"):
            f0 = o["failed"][0]
            detail = " | %s: %s" % (f0.get("name"), (f0.get("message") or "")[:200])
        elif o.get("error"):
            detail = " | " + str(o["error"])[:200]
        lines.append("%s %s params=%s %.0fs%s" % (
            status, o.get("strategy"), o.get("params"), o.get("duration_s", 0), detail))
    return "\n".join(lines)


def build_plan_messages(ctx, history, budget, schema_variant="full", include_source=True):
    """Assemble the plan-request messages for one round."""
    user_parts = [
        "## Task",
        "Reproduce a failure of flaky test: %s" % ctx["test"],
        "Project module: %s (Java %s, Maven)" % (ctx["module"], ctx["java"]),
        "Budget left: %d LLM calls, %d executions" % (budget["calls"], budget["execs"]),
    ]
    src = test_source_context(ctx) if include_source else ""
    if src:
        user_parts.append(src)
    cands = None
    try:
        import strategies
        cands = strategies.find_candidate_tests(ctx, limit=40)
    except Exception:
        pass
    if cands:
        user_parts.append("## Candidate co-tests in this module (usable in T3/T5)\n" + ", ".join(cands))
    user_parts.append("## Observations so far (most recent last)\n" + obs_summary(history[-2:]))
    user_parts.append(PLAN_SCHEMA)
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


def build_diagnose_messages(ctx, history, failure):
    user_parts = [
        "## Task",
        "The flaky test %s just failed. Diagnose its root cause." % ctx["test"],
        "Project module: %s" % ctx["module"],
        "## Run history\n" + obs_summary(history),
        "## Failure that was reproduced\n" + json.dumps(failure, indent=1, ensure_ascii=False)[:4000],
    ]
    src = test_source_context(ctx)
    if src:
        user_parts.append(src)
    user_parts.append(DIAGNOSE_TASK)
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


import json  # noqa: E402
