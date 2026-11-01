# -*- coding: utf-8 -*-
"""stressors: reversible system-level perturbations (T7 cpu/io stress, T11 hosts block)."""
import os
import subprocess
import sys
import time
from contextlib import contextmanager

HOSTS = "/etc/hosts"
HOSTS_BAK = "/etc/hosts.fabak"


@contextmanager
def stress(mode="cpu", cpus=2):
    """Run busy loops for the duration of the with-block."""
    procs = []
    try:
        if mode in ("cpu", "cpu-io"):
            for _ in range(cpus):
                procs.append(subprocess.Popen(
                    [sys.executable, "-c",
                     "import time\nwhile True: [i*i for i in range(5000)]"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        if mode == "io":
            procs.append(subprocess.Popen(
                ["dd", "if=/dev/zero", "of=/tmp/fabak_io.bin", "bs=1M", "count=1024",
                 "oflag=direct"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        yield
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()
        try:
            os.remove("/tmp/fabak_io.bin")
        except OSError:
            pass


@contextmanager
def block_hosts(hosts):
    """Append hosts to /etc/hosts for the duration of the with-block."""
    if not hosts or os.geteuid() != 0:
        yield
        return
    try:
        with open(HOSTS, encoding="utf-8") as f:
            orig = f.read()
        with open(HOSTS_BAK, "w", encoding="utf-8") as f:
            f.write(orig)
        with open(HOSTS, "a", encoding="utf-8") as f:
            for h in hosts:
                f.write("\n127.0.0.1 %s\n" % h)
        yield
    finally:
        try:
            os.replace(HOSTS_BAK, HOSTS)
        except OSError:
            pass


if __name__ == "__main__":
    with stress("cpu", 2):
        time.sleep(2)
    print("stress ok")
