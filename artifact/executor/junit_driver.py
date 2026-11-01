# -*- coding: utf-8 -*-
"""junit_driver: run one Maven test command and return a structured JSON observation.

Parses Surefire JUnit XML reports (and NonDex .nondex dirs) into
{strategy, params, exit_code, duration_s, failed[], passed, error, log_tail}.
"""
import json
import os
import re
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _strip_ansi(s):
    return ANSI.sub("", s)


def find_surefire_xmls(project_dir, module):
    """Collect TEST-*.xml files for the module (surefire-reports + .nondex)."""
    roots = []
    if module and module != ".":
        base = os.path.join(project_dir, module, "target")
    else:
        base = os.path.join(project_dir, "target")
    for sub in ["surefire-reports", ".nondex"]:
        roots.append(os.path.join(base, sub))
    # also scan all module target dirs (safety net for nested layouts)
    roots.append(project_dir)
    seen, out = set(), []
    for r in roots:
        if not os.path.isdir(r):
            continue
        for dp, _, fns in os.walk(r):
            if "surefire-reports" not in dp and ".nondex" not in dp:
                continue
            for fn in fns:
                if fn.startswith("TEST-") and fn.endswith(".xml"):
                    p = os.path.join(dp, fn)
                    if p not in seen:
                        seen.add(p)
                        out.append(p)
    return out


def parse_surefire(path):
    """Return list of {name, failure_message, stack} for failed tests in one XML."""
    try:
        tree = ET.parse(path)
    except Exception:
        return []
    fails = []
    root = tree.getroot()
    for tc in root.iter("testcase"):
        # NOTE: `or` chaining is wrong here — a childless <failure> element is
        # falsy (Element.__bool__ falls back to __len__), so the found element
        # would be discarded and the parse would report no failure at all.
        fail = tc.find("failure")
        if fail is None:
            fail = tc.find("error")
        if fail is None:
            continue
        msg = fail.get("message") or ""
        body = (fail.text or "")
        if fail is not None and len(fail):
            body = "".join(fail.itertext())
        stack = [l for l in body.splitlines() if l.strip()][:25]
        fails.append({"name": tc.get("name") or "", "classname": tc.get("classname") or "",
                      "message": (msg or "").strip()[:500], "stack": stack})
    return fails


def run_mvn(project_dir, args, module=".", java="11", timeout_s=config.RUN_TIMEOUT_S,
            env_extra=None, cwd=None, repo_local=None):
    """Run mvn; return (exit_code, stdout, duration_s)."""
    env = dict(os.environ)
    env["JAVA_HOME"] = config.JAVA_HOMES.get(java, config.JAVA_HOMES["11"])
    env["PATH"] = env["JAVA_HOME"] + "/bin:" + env.get("PATH", "")
    env.pop("TERM", None)  # jline-based test setups hang on stty/termcap when TERM is set
    env.setdefault("MAVEN_OPTS", "-Xmx2g")
    if repo_local:
        env["MAVEN_OPTS"] += " -Dmaven.repo.local=" + repo_local
    for k, v in (env_extra or {}).items():
        env[k] = v
    cmd = [config.MVN] + args + config.MVNOPTIONS.split()
    # jline terminal bypass: jline execs `stty ... < /dev/tty` from any JVM
    # that constructs a ConsoleReader; when that JVM's process group is not
    # the controlling pty's foreground group the stty child is stopped by
    # SIGTTOU and the JVM blocks forever. UnsupportedTerminal (checked by
    # TerminalFactory before TERM) removes the stty dependency entirely.
    # The -D covers the mvn JVM (testrunner paths); systemPropertiesFile
    # covers forked surefire JVMs (ignored harmlessly by old surefire).
    cmd += ["-Djline.terminal=jline.UnsupportedTerminal",
            "-Dsurefire.systemPropertiesFile=" + config.JLINE_PROPS]
    t0 = time.time()
    try:
        p = subprocess.Popen(cmd, cwd=cwd or project_dir, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL,  # forked JVMs must not block on our stdin
                             start_new_session=True, text=True, errors="replace")
        out, _ = p.communicate(timeout=timeout_s)
        code = p.returncode
    except subprocess.TimeoutExpired:
        # kill the whole process group: a hung forked JVM would otherwise
        # keep the stdout pipe open and p.communicate() would never return
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            p.kill()
        out = p.communicate()[0] or ""
        out += "\n[DRIVER] timeout after %ds" % timeout_s
        code = -9
    if isinstance(out, bytes):  # defensive: some Popen paths yield bytes
        out = out.decode("utf-8", "replace")
    return code, _strip_ansi(out), time.time() - t0


def find_testplugin_results(project_dir, module):
    """Collect iDFlakies test-runs JSON result files for the module."""
    base = os.path.join(project_dir, module) if module and module != "." else project_dir
    d = os.path.join(base, ".dtfixingtools", "test-runs", "results")
    if not os.path.isdir(d):
        return []
    out = []
    for fn in os.listdir(d):
        p = os.path.join(d, fn)
        if os.path.isfile(p):
            out.append(p)
    return out


def parse_testplugin_json(path):
    """Parse one ExecutionInfo JSON -> per-subrun entries.

    Each test executes num.runs times in the same JVM; entries are keyed
    '<test>:<subrun>'. Returns [{name, subrun, result, time, stack}].
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for key, r in (data.get("results") or {}).items():
        out.append({
            "name": r.get("name") or key,
            "subrun": key.rsplit(":", 1)[-1],
            "result": r.get("result", ""),
            "time": r.get("time"),
            "stack": r.get("stackTrace") or [],
        })
    return out


def find_testplugin_outputs(project_dir, module):
    """Collect the forked-JVM stdout files (contain assertion messages)."""
    base = os.path.join(project_dir, module) if module and module != "." else project_dir
    d = os.path.join(base, ".dtfixingtools", "test-runs", "output")
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, fn) for fn in os.listdir(d)
            if os.path.isfile(os.path.join(d, fn))]


def make_observation(strategy, params, code, out, duration, project_dir, module):
    if strategy == "T2":
        return _make_t2_observation(strategy, params, code, out, duration, project_dir, module)
    xmls = find_surefire_xmls(project_dir, module)
    # only keep xmls modified in the last run window. NO fallback to stale
    # xmls: a run that produced no new report (build failure, nothing ran)
    # must report zero tests, not historical results from other runs.
    now = time.time()
    fresh = [x for x in xmls if now - os.path.getmtime(x) < duration + 300]
    failed = []
    passed = 0
    for x in fresh:
        fails = parse_surefire(x)
        if fails:
            failed.extend(fails)
        try:
            tree = ET.parse(x)
            passed += sum(1 for _ in tree.getroot().iter("testcase"))
        except Exception:
            pass
    passed = max(passed - len(failed), 0)
    tail = "\n".join(out.splitlines()[-30:])
    return {
        "strategy": strategy,
        "params": params or {},
        "exit_code": code,
        "duration_s": round(duration, 1),
        "failed": failed,
        "passed": passed,
        "error": None if code in (0, 1) else "non-zero exit %s" % code,
        "log_tail": tail[-3000:],
    }


def _make_t2_observation(strategy, params, code, out, duration, project_dir, module):
    """Observation for the iDFlakies testplugin double-run: parse sub-run JSONs."""
    now = time.time()
    entries = []
    for p in find_testplugin_results(project_dir, module):
        if now - os.path.getmtime(p) < duration + 300:
            entries.extend(parse_testplugin_json(p))
    # assertion messages live in the forked-JVM output files
    out_text = []
    for p in find_testplugin_outputs(project_dir, module):
        if now - os.path.getmtime(p) < duration + 300:
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    out_text.append(f.read()[-6000:])
            except OSError:
                pass
    combined = "\n".join(out_text)
    failed = []
    passed = 0
    for e in entries:
        res = (e["result"] or "").upper()
        if res in ("ERROR", "FAILURE", "FAIL"):
            failed.append({
                "name": e["name"], "subrun": e["subrun"],
                "message": "", "stack": e["stack"][:25],
            })
        else:
            passed += 1
    # attach assertion messages found in forked output to matching failures
    import re as _re
    for f in failed:
        meth = f["name"].rsplit(".", 1)[-1]
        m = _re.search(r"(AssertionError[^\n]*|expected[^\n]*|AssertionFailedError[^\n]*)",
                       combined)
        if m:
            f["message"] = m.group(1).strip()[:500]
    tail = "\n".join(out.splitlines()[-30:])
    return {
        "strategy": strategy,
        "params": params or {},
        "exit_code": code,
        "duration_s": round(duration, 1),
        "failed": failed,
        "passed": passed,
        "error": None if code in (0, 1) else "non-zero exit %s" % code,
        "log_tail": tail[-3000:],
        "subruns": [{k: e[k] for k in ("name", "subrun", "result")} for e in entries],
    }


def run_test(project_dir, module, test_spec, strategy="T1", params=None,
             java="11", timeout_s=config.RUN_TIMEOUT_S, env_extra=None,
             surefire_opts=None, repo_local=None):
    """Run one test selection; return observation dict.

    test_spec: 'Class#method' / 'Class1,Class2' / 'Class#m1+Class#m2' (surefire syntax).
    """
    params = params or {}
    args = ["-pl", module, "test"]
    if test_spec:
        args += ["-Dtest=" + test_spec]
    for k, v in (surefire_opts or {}).items():
        args.append("-D%s=%s" % (k, v))
    code, out, dur = run_mvn(project_dir, args, module=module, java=java,
                             timeout_s=timeout_s, env_extra=env_extra,
                             repo_local=repo_local)
    return make_observation(strategy, params, code, out, dur, project_dir, module)


# the dataset's customized surefire: adds runOrder=testorder (runs the tests
# in the order given in -Dtest), shipped in the Flakym2 caches of OD projects
CUSTOM_SUREFIRE = ("org.apache.maven.plugins:maven-surefire-plugin:"
                   "3.0.0-M8-SNAPSHOT:test")


def run_ordered(project_dir, module, spec, strategy="ORD", params=None,
                java="11", timeout_s=None, repo_local=None):
    """Run the tests in `spec` (comma-separated) in that exact order, via the
    dataset's customized surefire (runOrder=testorder). One observation."""
    params = params or {}
    args = ["-pl", module, CUSTOM_SUREFIRE]
    if spec:
        args += ["-Dtest=" + spec]
    args += ["-Dsurefire.runOrder=testorder"]
    code, out, dur = run_mvn(project_dir, args, module=module, java=java,
                             timeout_s=timeout_s or config.RUN_TIMEOUT_S,
                             repo_local=repo_local)
    return make_observation(strategy, params, code, out, dur, project_dir, module)


if __name__ == "__main__":
    # smoke: run a test from a prepared workdir
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--module", default=".")
    ap.add_argument("--test", required=True)
    ap.add_argument("--java", default="11")
    ap.add_argument("--strategy", default="T1")
    ap.add_argument("--surefire", default="")
    args = ap.parse_args()
    sopts = {}
    if args.surefire:
        for kv in args.surefire.split(","):
            k, _, v = kv.partition("=")
            sopts[k] = v
    obs = run_test(args.project, args.module, args.test, strategy=args.strategy,
                   java=args.java, surefire_opts=sopts)
    print(json.dumps(obs, indent=2, ensure_ascii=False))
