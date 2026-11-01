# -*- coding: utf-8 -*-
"""rescue_build: 对已知构建失败的项目做针对性修复后重试构建。

三类已知失败（对应原机器 STATE.md）：
  1. Hadoop 系 protoc 缺失  -> 已装 /usr/local/bin/protoc 2.5.0，直接重试即可
  2. wildfly-naming 缺依赖 -> 在线 mvn 一次 fetch（repository.jboss.org 可达）
  3. fastjson2 testCompile 编译错误 -> 换 JDK 或检查具体错误

用法（WSL root）：
  export JAVA_HOME=/opt/tools/jdk8; python3 scripts/rescue_build.py [zip1 zip2 ...]
不传参数则自动扫描 workdir 下 build_ok=False 的项目。
"""
import csv, os, sys, json, time, subprocess, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "executor"))
import config, prepare

SUBSET = os.path.join(ROOT, "data", "subset.csv")


def load_row(zipname):
    with open(SUBSET, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["zip"] == zipname:
                return r
    return None


def failed_projects():
    out = []
    for d in os.listdir(config.WORKDIR):
        envp = os.path.join(config.WORKDIR, d, "build.env")
        if not os.path.exists(envp):
            continue
        try:
            info = json.load(open(envp))
        except Exception:
            continue
        if not info.get("build_ok"):
            out.append(d)
    return sorted(out)


def retry_prepare(zipname, row, online=False):
    """Delete build.env and re-prepare (optionally forcing online first)."""
    envp = os.path.join(config.WORKDIR, zipname, "build.env")
    if os.path.exists(envp):
        os.remove(envp)
    module = row["module"] or "."
    java = row["java"]
    t0 = time.time()
    if online:
        # 先在线 fetch 依赖（wildfly-naming 缺 jboss 定制依赖）
        info, tail = prepare.prepare(zipname, module, java, offline_pref=False)
    else:
        info, tail = prepare.prepare(zipname, module, java)
    status = "OK" if info["build_ok"] else "FAIL"
    print("[%s] %s (online=%s) %.0fs" % (status, zipname, online, time.time() - t0), flush=True)
    if not info["build_ok"]:
        print("    tail: " + tail[-300:], flush=True)
    return info["build_ok"]


def main():
    args = sys.argv[1:]
    if args:
        targets = args
    else:
        targets = failed_projects()
    print("待 rescue: %s" % targets, flush=True)

    for z in targets:
        row = load_row(z)
        if row is None:
            print("[skip] %s 不在 subset.csv" % z, flush=True)
            continue
        cat = row["category"]
        # 策略选择：wildfly 用在线，其余先离线重试（Hadoop protoc 已装好）
        if z.startswith("wildfly"):
            ok = retry_prepare(z, row, online=True)
            if not ok:
                # 在线失败再试离线
                ok = retry_prepare(z, row, online=False)
        else:
            ok = retry_prepare(z, row, online=False)
            if not ok:
                ok = retry_prepare(z, row, online=True)
        print("== %s: %s ==" % (z, "RESCUED" if ok else "STILL FAILING"), flush=True)


if __name__ == "__main__":
    main()
