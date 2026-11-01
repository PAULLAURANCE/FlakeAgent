# -*- coding: utf-8 -*-
"""patcher: inject a Thread.sleep into a Java method (T6) and revert it after.

Sleep is injected as the first statement of the chosen method body with a
try/catch guard. If the agent gives a method name, we resolve it; otherwise
we pick the method in the test class (or the class under test it exercises).
"""
import os
import re
import sys
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_SNIP = ('try { Thread.sleep(%dL); } catch (InterruptedException __fa) '
         '{ Thread.currentThread().interrupt(); }')

# Global lock serializing T6 sleep injection+revert. Without it, two workers
# injecting into the SAME file race on the .fabak backup: worker B overwrites
# worker A's backup, A's revert restores B's injected version, and B's revert
# finds no backup and skips — leaving B's sleep permanently in the source.
_PATCH_LOCK = threading.Lock()


def find_java_files(ctx, subdir="main"):
    base = os.path.join(ctx["flaky_dir"], ctx["module"]) if ctx["module"] != "." \
        else ctx["flaky_dir"]
    root = os.path.join(base, "src", subdir, "java")
    out = []
    if os.path.isdir(root):
        for dp, _, fns in os.walk(root):
            for fn in fns:
                if fn.endswith(".java"):
                    out.append(os.path.join(dp, fn))
    return out


def _method_bodies(src):
    """Crude brace-balanced scan: return [(method_decl_line, open_brace_pos)]."""
    decl = re.compile(
        r"((?:public|protected|private|static|final|synchronized|\s)*"
        r"[\w<>\[\]?.,\s]+\s+(\w+)\s*\([^;{]*\)\s*\{)")
    res = []
    for m in decl.finditer(src):
        # ensure the brace belongs to a method (heuristic: word before '(' is a name)
        res.append((m.group(2), m.end() - 1))
    return res


def inject_sleep(ctx, method, ms):
    """Insert sleep at start of `method` body. Returns patch info or None."""
    files = find_java_files(ctx, "main") + find_java_files(ctx, "test")
    # prefer test class file
    cls_simple = ctx["test"].split("#")[0].split(".")[-1]
    files.sort(key=lambda f: 0 if f.endswith(cls_simple + ".java") else 1)
    for path in files:
        with _PATCH_LOCK:
            # if a previous injection on this file was never reverted, restore it
            # first so we always inject into a clean source.
            backup = path + ".fabak"
            if os.path.exists(backup):
                os.replace(backup, path)
            src = open(path, encoding="utf-8", errors="ignore").read()
            bodies = _method_bodies(src)
            target = None
            for name, brace in bodies:
                if method and name == method:
                    target = brace
                    break
            if target is None and not method and bodies:
                target = bodies[0][1]
            if target is None:
                continue
            # insert after the opening brace, preserving indentation
            nl = src.rfind("\n", 0, target)
            indent = src[nl + 1:target]
            pad = indent + "    "
            snippet = _SNIP % ms
            injected = src[:target + 1] + "\n" + pad + snippet + src[target + 1:]
            with open(backup, "w", encoding="utf-8") as f:
                f.write(src)
            with open(path, "w", encoding="utf-8") as f:
                f.write(injected)
            return {"file": path, "backup": backup,
                    "method": method or bodies[0][0], "sleep_ms": ms}
    return None


def revert(ctx, patch):
    with _PATCH_LOCK:
        if patch and os.path.exists(patch["backup"]):
            os.replace(patch["backup"], patch["file"])
            # Bump mtime into the future so Maven's incremental compiler sees the
            # reverted source as newer than the stale injected .class left in
            # target/ and recompiles it on the next `mvn test`. Without this, the
            # next run reuses the injected bytecode and reports spurious failures.
            future = time.time() + 10
            os.utime(patch["file"], (future, future))


def rebuild(ctx, offline=True, m2=None):
    """Recompile after patching: mvn -pl M -am install -DskipTests."""
    import subprocess
    import config
    env = dict(os.environ)
    env["JAVA_HOME"] = config.JAVA_HOMES.get(ctx["java"], config.JAVA_HOMES["11"])
    env["PATH"] = env["JAVA_HOME"] + "/bin:" + env.get("PATH", "")
    args = ["-pl", ctx["module"], "-am", "install", "-DskipTests"]
    if offline:
        args.append("-o")
    if m2:
        env["MAVEN_OPTS"] = env.get("MAVEN_OPTS", "") + " -Dmaven.repo.local=" + m2
    cmd = [config.MVN] + args + config.MVNOPTIONS.split()
    try:
        p = subprocess.run(cmd, cwd=ctx["flaky_dir"], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=config.BUILD_TIMEOUT_S, text=True, errors="replace")
        return p.returncode == 0, (p.stdout or "")[-3000:]
    except subprocess.TimeoutExpired as e:
        return False, ((e.stdout or "") + "\ntimeout")[-3000:]
