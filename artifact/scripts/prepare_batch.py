# -*- coding: utf-8 -*-
"""prepare_batch: 批量解压+离线构建已完整下载的 zip（2 并发，跳过已构建）。

在新机器上替代原 prepare 的一次性编排。用法（WSL root）：
  export JAVA_HOME=/opt/tools/jdk8; python3 scripts/prepare_batch.py
"""
import csv, os, sys, json, time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "executor"))
import config, prepare

SUBSET = os.path.join(ROOT, "data", "subset.csv")
WINZIPS = "/mnt/c/Users/histings/Desktop/FSE_autoresearch/workdir/zips"


def load_zips():
    zips = {}
    with open(SUBSET, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            z = r["zip"]
            if z not in zips:
                zips[z] = {"mb": float(r["zip_mb"]) * 1e6,
                           "module": r["module"] or ".",
                           "java": r["java"], "cat": r["category"]}
    return zips


zips = load_zips()


def is_complete(key):
    mb = zips[key]["mb"]
    p = os.path.join(WINZIPS, key + ".zip")
    if not os.path.exists(p):
        return False
    return abs(os.path.getsize(p) - mb) / mb < 0.02


def already_built(key):
    envp = os.path.join(config.WORKDIR, key, "build.env")
    if os.path.exists(envp):
        try:
            return json.load(open(envp)).get("build_ok")
        except Exception:
            return False
    return False


def do_prepare(key):
    z = zips[key]
    t0 = time.time()
    try:
        info, tail = prepare.prepare(key, z["module"], z["java"])
        status = "OK" if info["build_ok"] else "FAIL"
        line = "[%s] %s (cat=%s java=%s) %.0fs" % (
            status, key, z["cat"], z["java"], time.time() - t0)
        if not info["build_ok"]:
            line += "\n    tail: " + tail[-200:]
        return line
    except Exception as ex:
        return "[EXC] %s: %s" % (key, ex)


def main():
    todo = [k for k in sorted(zips) if is_complete(k) and not already_built(k)]
    print("待构建: %d 个" % len(todo), flush=True)
    ok = fail = 0
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(do_prepare, k): k for k in todo}
        for fut in as_completed(futs):
            r = fut.result()
            print(r, flush=True)
            if r.startswith("[OK]"):
                ok += 1
            else:
                fail += 1
    print("=== 全部完成：成功 %d / 失败 %d ===" % (ok, fail), flush=True)


if __name__ == "__main__":
    main()
