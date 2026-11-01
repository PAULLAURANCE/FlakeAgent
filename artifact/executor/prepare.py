# -*- coding: utf-8 -*-
"""prepare: extract a ReproFlake zip and build the flaky version once.

Outputs workdir/<zipname>/build.env with module/java/repo info, and builds
the module with `mvn install -DskipTests` (offline with the zip's Flakym2
cache when present, online via Aliyun mirror otherwise).
"""
import json
import os
import shutil
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


def extract_zip(zipname):
    zippath = os.path.join(config.ZIPS_DIR, zipname + ".zip")
    if not os.path.exists(zippath):
        raise FileNotFoundError(zippath)
    out = os.path.join(config.WORKDIR, zipname)
    if os.path.exists(os.path.join(out, "Flaky")):
        return out  # already extracted
    os.makedirs(out, exist_ok=True)
    with zipfile.ZipFile(zippath) as z:
        root = z.namelist()[0].split("/")[0]
        z.extractall(out)
    inner = os.path.join(out, root)
    if os.path.isdir(inner) and inner != out:
        for e in os.listdir(inner):
            shutil.move(os.path.join(inner, e), os.path.join(out, e))
        os.rmdir(inner)
    return out


def flaky_dir(project_dir):
    return os.path.join(project_dir, "Flaky")


def find_m2_cache(project_dir):
    """Locate the cached maven repository inside the zip.

    Returns the REPOSITORY dir (the one containing org/, com/...). Handles
    Flakym2/.m2/repository, Flakym2/repository, Flakym2/.m2 and Flakym2 itself.
    """
    for cand in [os.path.join(project_dir, "Flakym2", ".m2", "repository"),
                 os.path.join(project_dir, "Flakym2", "repository"),
                 os.path.join(project_dir, "Flakym2", ".m2"),
                 os.path.join(project_dir, "Flakym2")]:
        if os.path.isdir(cand):
            return cand
    return None


# edu.illinois.cs artifacts needed by the T2 testplugin mechanism; the dataset
# built them into the NIO/OD project caches but they are absent from TD/ID ones.
T2_ARTIFACTS = [
    "edu/illinois/cs/testrunner-maven-plugin",
    "edu/illinois/cs/testrunner-running",
    "edu/illinois/cs/testrunner-core-plugin",
    "edu/illinois/cs/idflakies",
]


def inject_t2_artifacts(m2):
    """Copy the T2 plugin artifacts from the global repo into a zip cache (no-clobber)."""
    src = os.path.expanduser("~/.m2/repository")
    dst = m2
    os.makedirs(dst, exist_ok=True)
    n = 0
    for rel in T2_ARTIFACTS:
        s, d = os.path.join(src, rel), os.path.join(dst, rel)
        if not os.path.isdir(s):
            continue
        for dp, _, fns in os.walk(s):
            rd = os.path.relpath(dp, s)
            os.makedirs(os.path.join(d, rd), exist_ok=True)
            for fn in fns:
                tgt = os.path.join(d, rd, fn)
                if not os.path.exists(tgt):
                    shutil.copy2(os.path.join(dp, fn), tgt)
                    n += 1
    return n


def detect_java(project_dir):
    """Infer Java version from pom properties / toolchains; default 11."""
    pom = os.path.join(flaky_dir(project_dir), "pom.xml")
    if not os.path.exists(pom):
        return "11"
    txt = open(pom, encoding="utf-8", errors="ignore").read()
    if "<maven.compiler.source>1.8" in txt or "<java.version>1.8" in txt or "<source>1.8" in txt:
        return "8"
    if "<maven.compiler.source>17" in txt or "<java.version>17" in txt or "<source>17" in txt:
        return "17"
    return "11"


def build_project(project_dir, module, java, offline, repo_local, log_path):
    """One-time build: mvn -pl M -am install -DskipTests. Returns (ok, log_tail)."""
    env = dict(os.environ)
    env["JAVA_HOME"] = config.JAVA_HOMES.get(java, config.JAVA_HOMES["11"])
    env["PATH"] = env["JAVA_HOME"] + "/bin:" + env.get("PATH", "")
    env.setdefault("MAVEN_OPTS", "-Xmx3g")
    if repo_local:
        env.setdefault("MAVEN_OPTS", env["MAVEN_OPTS"] + " -Dmaven.repo.local=" + repo_local)
    args = ["-pl", module, "-am", "install", "-DskipTests"]
    if offline:
        args.append("-o")
    cmd = [config.MVN] + args + config.MVNOPTIONS.split()
    try:
        p = subprocess.run(cmd, cwd=flaky_dir(project_dir), env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=config.BUILD_TIMEOUT_S, text=True, errors="replace")
        ok, out = p.returncode == 0, p.stdout or ""
    except subprocess.TimeoutExpired as e:
        so = e.stdout
        if isinstance(so, bytes):
            so = so.decode("utf-8", "replace")
        ok, out = False, (so or "") + "\n[PREPARE] build timeout"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(out)
    tail = "\n".join(out.splitlines()[-15:])
    return ok, tail


def prepare(zipname, module, java=None, offline_pref=True):
    """Full prep; returns dict with env info and build status."""
    project_dir = extract_zip(zipname)
    fdir = flaky_dir(project_dir)
    m2 = find_m2_cache(project_dir)
    if m2:
        inject_t2_artifacts(m2)
    java = java or detect_java(project_dir)
    log_path = os.path.join(project_dir, "build.log")
    env_path = os.path.join(project_dir, "build.env")

    ok, tail = build_project(project_dir, module, java,
                             offline=m2 is not None and offline_pref,
                             repo_local=m2, log_path=log_path)
    if not ok and m2:
        # fallback: online mode (aliyun mirror handles missing deps)
        ok, tail = build_project(project_dir, module, java, offline=False,
                                 repo_local=m2, log_path=log_path)
    info = {
        "zip": zipname, "module": module, "java": java,
        "m2": m2, "repo_local": m2, "build_ok": ok, "project_dir": project_dir,
        "flaky_dir": fdir, "log": log_path,
    }
    with open(env_path, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    return info, tail


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--module", default=".")
    ap.add_argument("--java", default=None)
    args = ap.parse_args()
    info, tail = prepare(args.zip, args.module, args.java)
    print(json.dumps({k: v for k, v in info.items() if k != "log"}, indent=2))
    print("---- build tail ----")
    print(tail)
