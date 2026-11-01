# -*- coding: utf-8 -*-
"""clean_td_bytecode: force Maven to recompile the TD workdirs' reverted sources.

The TD gate applies ReproFlake's FlakyCodeChange.patch (Thread.sleep injection),
compiles it into target/ (and, for src/main patches, installs the injected jar
into Flakym2), then reverts only the *source*. The agent's later `mvn test` is
incremental and reuses the stale injected .class -> spurious T1 reproductions.

Fix: bump the mtime of every patched source file into the future so Maven's
incremental compiler recompiles it on the next run. For src/main patches whose
patched module differs from the test module (cross-module, e.g. RATIS-1363), the
stale jar in m2 must ALSO be reinstalled, so we reinstall the patched module.

Run from WSL: python3 scripts/clean_td_bytecode.py
"""
import csv
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
WORKDIR = "/root/flakeagent/workdir"
SUBSET = os.path.join(ROOT, "data", "subset.csv")

sys.path.insert(0, os.path.join(ROOT, "executor"))
import config  # noqa: E402


def touched_files(zipname):
    """Parse FlakyCodeChange.patch -> list of absolute Flaky source paths."""
    pp = os.path.join(WORKDIR, zipname, "FlakyCodeChange.patch")
    if not os.path.exists(pp):
        return []
    flaky_dir = os.path.join(WORKDIR, zipname, "Flaky")
    out = set()
    for line in open(pp, encoding="utf-8", errors="ignore"):
        line = line.rstrip("\n")
        for pref in ("+++ FlakyCodeChange/", "--- Flaky/"):
            if line.startswith(pref):
                rel = line[len(pref):].split("\t", 1)[0]
                out.add(os.path.join(flaky_dir, rel))
    return sorted(out)


def main_module(zipname):
    """Return the src/main modules named in the patch (for cross-module check)."""
    pp = os.path.join(WORKDIR, zipname, "FlakyCodeChange.patch")
    mods = set()
    if not os.path.exists(pp):
        return mods
    for line in open(pp, encoding="utf-8", errors="ignore"):
        if line.startswith("+++ ") and "/src/main/" in line:
            rel = line.split("+++ ", 1)[1].split("/src/main/")[0]
            mods.add(rel.replace("FlakyCodeChange/", ""))
    return mods


def run_mvn(zipname, module, repo_local):
    env = dict(os.environ)
    env["JAVA_HOME"] = config.JAVA_HOMES.get("8", config.JAVA_HOMES["11"])
    env["PATH"] = env["JAVA_HOME"] + "/bin:" + env.get("PATH", "")
    env["MAVEN_OPTS"] = env.get("MAVEN_OPTS", "") + " -Dmaven.repo.local=" + repo_local
    flaky = os.path.join(WORKDIR, zipname, "Flaky")
    cmd = [config.MVN, "-pl", module, "install", "-DskipTests", "-o"] + config.MVNOPTIONS.split()
    print("[clean] %s -> %s" % (zipname, " ".join(cmd[1:4])), flush=True)
    try:
        p = subprocess.run(cmd, cwd=flaky, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=config.BUILD_TIMEOUT_S,
                           text=True, errors="replace")
        ok = p.returncode == 0
        print("[clean]   rc=%d" % p.returncode, flush=True)
        return ok
    except subprocess.TimeoutExpired as e:
        print("[clean]   TIMEOUT", flush=True)
        return False


def main():
    future = time.time() + 10
    rows = [r for r in csv.DictReader(open(SUBSET, encoding="utf-8"))
            if r["category"] == "td"]
    touched = 0
    reinstalls = []
    for r in rows:
        z = r["zip"]
        # only gate-passed workdirs are in the agent set
        be = os.path.join(WORKDIR, z, "build.env")
        if not (os.path.exists(be)):
            continue
        try:
            info = json.load(open(be, encoding="utf-8"))
        except Exception:
            continue
        if not info.get("build_ok"):
            continue
        files = touched_files(z)
        for f in files:
            if os.path.exists(f):
                os.utime(f, (future, future))
                touched += 1
        # cross-module src/main -> reinstall the patched module cleanly
        mm = main_module(z)
        test_mod = r["module"]
        for m in mm:
            if m and m != test_mod:
                reinstalls.append((z, m, info.get("repo_local")))
    print("[clean] touched %d source files" % touched, flush=True)
    for z, m, m2 in reinstalls:
        run_mvn(z, m, m2)
    if reinstalls:
        print("[clean] reinstalled %d cross-module src/main modules" % len(reinstalls), flush=True)
    print("[clean] done", flush=True)


if __name__ == "__main__":
    main()
