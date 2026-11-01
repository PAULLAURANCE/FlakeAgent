# -*- coding: utf-8 -*-
"""The 12 strategy templates (T1..T12). Each maps agent-chosen params to
concrete local executions, returning observation dicts.

Executor-side implementations are deterministic; the LLM only selects the
strategy id and its parameters.
"""
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import junit_driver as jd
import patcher
import stressors

STRATEGY_IDS = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10", "T11", "T12"]

# Strategy families for the anti-degeneracy rules (paper Section 4.5):
# order (T3,T4,T5,T10), timing/resource (T6,T7,T8,T9), nondeterminism (T12),
# amplification (T1,T2).
FAMILIES = {"order": {"T3", "T4", "T5", "T10"},
            "timing": {"T6", "T7", "T8", "T9"},
            "nondet": {"T12"},
            "amplify": {"T1", "T2"}}


def family_of(s):
    for f, ids in FAMILIES.items():
        if s in ids:
            return f
    return None


def family_switch(s, valid=None):
    """Return a strategy from a different family than s (deterministic)."""
    valid = set(valid or STRATEGY_IDS)
    fam = family_of(s)
    for f, ids in FAMILIES.items():
        if f == fam:
            continue
        for t in ids:
            if t in valid:
                return t
    return next(iter(valid))


def _ctx_test(ctx):
    return ctx["test"]  # 'pkg.Class#method'


def _obs(strategy, params, code, out, dur, ctx, project_dir=None, module=None):
    return jd.make_observation(strategy, params, code, out, dur,
                               project_dir or ctx["flaky_dir"],
                               module or ctx["module"])


def find_candidate_tests(ctx, limit=50):
    """List candidate test specs in the module (for T3/T5 co-test choice)."""
    src = os.path.join(ctx["flaky_dir"], ctx["module"]) if ctx["module"] != "." \
        else ctx["flaky_dir"]
    roots = []
    for cand in [os.path.join(src, "src", "test", "java"),
                 os.path.join(ctx["flaky_dir"], "src", "test", "java")]:
        if os.path.isdir(cand):
            roots.append(cand)
    specs = set()
    for r in roots:
        for dp, _, fns in os.walk(r):
            for fn in fns:
                if fn.endswith("Test.java") or fn.endswith("Tests.java") or fn.endswith("IT.java"):
                    rel = os.path.relpath(os.path.join(dp, fn), r)
                    cls = rel[:-5].replace(os.sep, ".")
                    specs.add(cls)
    specs.discard(_ctx_test(ctx).split("#")[0])
    return sorted(specs)[:limit]


# ---------------- T1: rerun-isolated ----------------
def t1_rerun(ctx, params):
    repeats = max(1, min(int(params.get("repeats", 1)), 3))
    obs = None
    for i in range(repeats):
        obs = jd.run_test(ctx["flaky_dir"], ctx["module"], _ctx_test(ctx),
                          strategy="T1", params={"repeats": repeats, "run": i + 1},
                          java=ctx["java"])
        if obs["failed"]:
            break
    return [obs]


# ---------------- T2: same-JVM double-run (iDFlakies testplugin, dataset mechanism) ----------------
TESTRUNNER_PLUGIN_BLOCK = """<plugin>
                <groupId>edu.illinois.cs</groupId>
                <artifactId>testrunner-maven-plugin</artifactId>
                <version>1.4-SNAPSHOT</version>
                <dependencies>
                    <dependency>
                        <groupId>edu.illinois.cs</groupId>
                        <artifactId>idflakies</artifactId>
                        <version>1.2.0-SNAPSHOT</version>
                    </dependency>
                </dependencies>
                <configuration>
                    <className>edu.illinois.cs.dt.tools.detection.DetectorPlugin</className>
                </configuration>
            </plugin>"""


def _testrunner_available(ctx):
    """Is the iDFlakies testrunner plugin usable from this zip's dependency
    cache? Some OD zips ship the plugin jar but not the testrunner library
    artifact it depends on (edu.illinois.cs:testrunner); running testplugin
    there fails at resolution and leaves the pom edited behind it."""
    repo = ctx.get("repo_local") or ""
    if not repo:
        return True  # no repo override: assume present (falls back to resolution errors)
    # need the plugin itself AND the library artifact it depends on
    return (os.path.isdir(os.path.join(repo, "edu", "illinois", "cs",
                                       "testrunner-maven-plugin"))
            and os.path.isdir(os.path.join(repo, "edu", "illinois", "cs",
                                           "testrunner")))


def _pom_path(ctx):
    module = ctx["module"]
    base = os.path.join(ctx["flaky_dir"], module) if module and module != "." \
        else ctx["flaky_dir"]
    return os.path.join(base, "pom.xml")


def ensure_t2_pom(ctx):
    """Ensure the module pom declares the testrunner plugin (dataset-injected
    for NIO/OD projects; absent in TD/ID ones). Idempotent; backs the original
    pom up so restore_t2_pom can undo the edit. Returns True on ok."""
    pom = _pom_path(ctx)
    if not os.path.exists(pom):
        return False
    bak = pom + ".flakeagent.bak"
    if not os.path.exists(bak):
        with open(pom, "rb") as f:
            shutil.copyfileobj(f, open(bak, "wb"))
    with open(pom, encoding="utf-8", errors="ignore") as f:
        txt = f.read()
    if "testrunner-maven-plugin" in txt:
        return True
    block = TESTRUNNER_PLUGIN_BLOCK
    if "<build>" in txt and "</build>" in txt:
        if "<plugins>" in txt.split("</build>")[0].split("<build>")[-1]:
            txt = txt.replace("</plugins>", "\n" + block + "\n        </plugins>", 1)
        else:
            insert = "<build><plugins>\n" + block + "\n        </plugins></build>"
            txt = txt.replace("</build>", insert, 1)
    else:
        txt = txt.replace("</project>", "<build><plugins>\n" + block
                          + "\n        </plugins></build>\n</project>", 1)
    with open(pom, "w", encoding="utf-8") as f:
        f.write(txt)
    return True


def restore_t2_pom(ctx):
    """Undo the ensure_t2_pom edit (the injected plugin block can break builds
    that run sortpom:verify on the pom). Safe no-op if nothing to restore."""
    pom = _pom_path(ctx)
    bak = pom + ".flakeagent.bak"
    if os.path.exists(bak):
        shutil.copyfile(bak, pom)
        os.remove(bak)


def t2_double(ctx, params):
    runs = max(2, min(int(params.get("runs", 2)), 4))
    module = ctx["module"]
    base = os.path.join(ctx["flaky_dir"], module) if module and module != "." \
        else ctx["flaky_dir"]
    dt_dir = os.path.join(base, ".dtfixingtools")
    if os.path.isdir(dt_dir):
        shutil.rmtree(dt_dir)  # fresh state per invocation (dataset moves it away)
    os.makedirs(dt_dir)
    with open(os.path.join(dt_dir, "original-order"), "w") as f:
        f.write(_ctx_test(ctx).replace("#", "."))
    det = ["-Ddt.detector.original_order.all_must_pass=false",
           "-Ddt.randomize.rounds=0",
           "-Ddt.detector.original_order.retry_count=1",
           "-Dtestplugin.runner.idempotent.num.runs=%d" % runs,
           "-Dtestplugin.runner.consec.idempotent=true",
           "-Ddt.detector.forceJUnit4=true",
           "-Ddetector.detector_type=original"]
    if not _testrunner_available(ctx):
        return [_obs("T2", {"runs": runs}, -2,
                     "testrunner plugin not in this project's dependency cache", 0, ctx)]
    if not ensure_t2_pom(ctx):
        return [_obs("T2", {"runs": runs}, -2, "no pom to configure testplugin", 0, ctx)]
    try:
        args = ["-pl", module, "testrunner:testplugin"] + det
        code, out, dur = jd.run_mvn(ctx["flaky_dir"], args, module=module,
                                    java=ctx["java"], repo_local=ctx.get("repo_local"))
    finally:
        restore_t2_pom(ctx)
    return [_obs("T2", {"runs": runs}, code, out, dur, ctx)]


def run_testplugin_order(ctx, tests, strategy="ORD-TR", params=None,
                         java=None, repo_local=None):
    """Run `tests` once, in the given order, in the same JVM via the iDFlakies
    testrunner plugin. Fallback for ordered runs when a zip's cache lacks the
    dataset's custom surefire. Returns one observation."""
    module = ctx["module"]
    base = os.path.join(ctx["flaky_dir"], module) if module and module != "." \
        else ctx["flaky_dir"]
    dt_dir = os.path.join(base, ".dtfixingtools")
    if os.path.isdir(dt_dir):
        shutil.rmtree(dt_dir)
    os.makedirs(dt_dir)
    with open(os.path.join(dt_dir, "original-order"), "w") as f:
        f.write("\n".join(t.replace("#", ".") for t in tests if t))
    det = ["-Ddt.detector.original_order.all_must_pass=false",
           "-Ddt.randomize.rounds=0",
           "-Ddt.detector.original_order.retry_count=1",
           "-Dtestplugin.runner.idempotent.num.runs=1",
           "-Ddt.detector.forceJUnit4=true",
           "-Ddetector.detector_type=original"]
    if not _testrunner_available(ctx):
        return _obs("ORD-TR", params or {}, -2,
                    "testrunner plugin not in this project's dependency cache", 0, ctx)
    if not ensure_t2_pom(ctx):
        return _obs("ORD-TR", params or {}, -2, "no pom to configure testplugin", 0, ctx)
    try:
        args = ["-pl", module, "testrunner:testplugin"] + det
        code, out, dur = jd.run_mvn(ctx["flaky_dir"], args, module=module,
                                    java=java or ctx["java"],
                                    repo_local=repo_local or ctx.get("repo_local"))
    finally:
        restore_t2_pom(ctx)
    return _obs("ORD-TR", params or {}, code, out, dur, ctx)


# ---------------- T3: order-permutation ----------------
def t3_order(ctx, params):
    cotests = [c for c in (params.get("cotests") or []) if c]
    if not cotests:
        cands = find_candidate_tests(ctx, limit=8)
        cotests = cands[:2]
    spec = ",".join(cotests + [_ctx_test(ctx).split("#")[0]])
    obs = jd.run_ordered(ctx["flaky_dir"], ctx["module"], spec,
                         strategy="T3", params={"cotests": cotests},
                         java=ctx["java"],
                         repo_local=ctx.get("repo_local"))
    if obs.get("error") and "could not be resolved" in (obs.get("log_tail") or ""):
        obs = run_testplugin_order(ctx, cotests + [_ctx_test(ctx)],
                                   strategy="T3", params={"cotests": cotests})
    return [obs]


# ---------------- T4: random-suite-order ----------------
def t4_random_suite(ctx, params):
    seed = int(params.get("seed", int(time.time()) % 100000))
    obs = jd.run_test(ctx["flaky_dir"], ctx["module"], None,
                      strategy="T4", params={"seed": seed},
                      java=ctx["java"], timeout_s=config.RUN_TIMEOUT_S * 2,
                      surefire_opts={"surefire.runOrder": "random",
                                     "surefire.runOrder.random.seed": seed},
                      repo_local=ctx.get("repo_local"))
    return [obs]


# ---------------- T5: polluter-victim ----------------
def t5_polluter(ctx, params):
    polluter = params.get("polluter") or ""
    if not polluter:
        cands = find_candidate_tests(ctx, limit=6)
        if not cands:
            return [_obs("T5", {"polluter": None}, -2, "no polluter candidate", 0, ctx)]
        polluter = cands[0]
    victim = _ctx_test(ctx)
    if "#" in polluter and "#" in victim:
        # both are method-level: run P#m1,V#m2 in order (gate-proven for
        # sibling-method polluters like ShellSetInstanceTest)
        spec = "%s,%s" % (polluter, victim)
    else:
        spec = "%s,%s" % (polluter.split("#")[0], victim.split("#")[0])
    obs = jd.run_ordered(ctx["flaky_dir"], ctx["module"], spec,
                         strategy="T5", params={"polluter": polluter},
                         java=ctx["java"],
                         repo_local=ctx.get("repo_local"))
    if obs.get("error") and "could not be resolved" in (obs.get("log_tail") or ""):
        obs = run_testplugin_order(ctx, [polluter, _ctx_test(ctx)],
                                   strategy="T5", params={"polluter": polluter})
    return [obs]


# ---------------- T6: sleep-injection ----------------
def t6_sleep(ctx, params):
    ms = max(10, min(int(params.get("sleep_ms", 500)), 20000))
    method = params.get("target_method") or ""
    patch = patcher.inject_sleep(ctx, method, ms)
    if patch is None:
        return [_obs("T6", {"sleep_ms": ms, "target_method": method}, -2,
                     "patcher: target method not found", 0, ctx)]
    try:
        obs = jd.run_test(ctx["flaky_dir"], ctx["module"], _ctx_test(ctx),
                          strategy="T6", params={"sleep_ms": ms, "target_method": patch["method"]},
                          java=ctx["java"], repo_local=ctx.get("repo_local"))
    finally:
        patcher.revert(ctx, patch)
    return [obs]


# ---------------- T7: system-stress ----------------
def t7_stress(ctx, params):
    mode = params.get("mode", "cpu")
    cpus = max(1, min(int(params.get("cpus", 2)), 6))
    with stressors.stress(mode, cpus):
        obs = jd.run_test(ctx["flaky_dir"], ctx["module"], _ctx_test(ctx),
                          strategy="T7", params={"mode": mode, "cpus": cpus},
                          java=ctx["java"], repo_local=ctx.get("repo_local"))
    return [obs]


# ---------------- T8: env-manipulation ----------------
def t8_env(ctx, params):
    env_map = dict(params.get("env") or {})
    # whitelist sane keys to avoid shell-injection-ish env damage
    allowed = {"TZ", "LANG", "LC_ALL", "LC_TIME", "MALLOC_ARENA_MAX",
               "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "LINES", "COLUMNS", "HOME"}
    env_map = {k: v for k, v in env_map.items() if k in allowed}
    if not env_map:
        env_map = {"TZ": "UTC"}
    obs = jd.run_test(ctx["flaky_dir"], ctx["module"], _ctx_test(ctx),
                      strategy="T8", params={"env": env_map},
                      java=ctx["java"], env_extra=env_map,
                      repo_local=ctx.get("repo_local"))
    return [obs]


# ---------------- T9: resource-limit ----------------
def t9_limit(ctx, params):
    xmx = params.get("xmx", "256m")
    fork = params.get("fork_count", 0)
    env_extra = {"MAVEN_OPTS": "-Xmx%s" % xmx}
    obs = jd.run_test(ctx["flaky_dir"], ctx["module"], _ctx_test(ctx),
                      strategy="T9", params={"xmx": xmx, "fork_count": fork},
                      java=ctx["java"], env_extra=env_extra,
                      surefire_opts={"surefire.forkCount": fork, "reuseForks": "false"},
                      repo_local=ctx.get("repo_local"))
    return [obs]


# ---------------- T10: parallel-execution ----------------
def t10_parallel(ctx, params):
    parallel = params.get("parallel", "classes")
    threads = max(1, min(int(params.get("thread_count", 4)), 8))
    spec = _ctx_test(ctx).split("#")[0]  # whole class parallelizes within itself
    obs = jd.run_test(ctx["flaky_dir"], ctx["module"], spec,
                      strategy="T10", params={"parallel": parallel, "thread_count": threads},
                      java=ctx["java"],
                      surefire_opts={"surefire.parallel": parallel,
                                     "surefire.threadCount": threads},
                      repo_local=ctx.get("repo_local"))
    return [obs]


# ---------------- T11: external-block (hosts-file based) ----------------
def t11_block(ctx, params):
    hosts = [h for h in (params.get("hosts") or []) if h and "." in h][:5]
    with stressors.block_hosts(hosts):
        obs = jd.run_test(ctx["flaky_dir"], ctx["module"], _ctx_test(ctx),
                          strategy="T11", params={"hosts": hosts},
                          java=ctx["java"], repo_local=ctx.get("repo_local"))
    return [obs]


# ---------------- T12: nondex-seed ----------------
def t12_nondex(ctx, params):
    seed = str(params.get("seed", 933178)).strip() or "933178"
    rounds = max(10, min(int(params.get("rounds", 100)), 100))
    args = ["-pl", ctx["module"],
            "edu.illinois:nondex-maven-plugin:2.1.1:nondex",
            "-DnondexSeed=" + seed, "-DnondexRuns=%d" % rounds,
            "-DnondexMode=ONE", "-Dtest=%s" % _ctx_test(ctx)]
    code, out, dur = jd.run_mvn(ctx["flaky_dir"], args, module=ctx["module"],
                                java=ctx["java"], timeout_s=config.RUN_TIMEOUT_S * 2,
                                repo_local=ctx.get("repo_local"))
    return [_obs("T12", {"seed": seed, "rounds": rounds}, code, out, dur, ctx)]


RUNNERS = {
    "T1": t1_rerun, "T2": t2_double, "T3": t3_order, "T4": t4_random_suite,
    "T5": t5_polluter, "T6": t6_sleep, "T7": t7_stress, "T8": t8_env,
    "T9": t9_limit, "T10": t10_parallel, "T11": t11_block, "T12": t12_nondex,
}


def execute_strategy(ctx, strategy_id, params):
    """Run one strategy; returns list of observation dicts."""
    if strategy_id not in RUNNERS:
        return [_obs(strategy_id, params, -3, "unknown strategy", 0, ctx)]
    return RUNNERS[strategy_id](ctx, params or {})


def context(project_dir, module, test, java):
    return {"flaky_dir": project_dir, "module": module, "test": test, "java": java}
