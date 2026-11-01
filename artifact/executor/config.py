# -*- coding: utf-8 -*-
"""Shared configuration for the FlakeAgent executor (runs inside WSL Ubuntu)."""
import os

# WSL-side paths
ZIPS_DIR = "/root/flakeagent/zips"
WORKDIR = "/root/flakeagent/workdir"
# Windows-side paths (for the orchestrator, may be unused inside WSL)
if os.name == "nt":
    ZIPS_DIR = r"C:\Users\histings\Desktop\FSE_autoresearch\workdir\zips"
    WORKDIR = r"C:\Users\histings\Desktop\FSE_autoresearch\workdir"

JAVA_HOMES = {
    "8":  "/opt/tools/jdk8",
    "11": "/usr/lib/jvm/java-11-openjdk-amd64",
    "17": "/usr/lib/jvm/java-17-openjdk-amd64",
}
MVN = "/opt/tools/maven/bin/mvn"

# same flags the ReproFlake dataset uses
MVNOPTIONS = (
    "-Ddependency-check.skip=true -Dgpg.skip=true -DfailIfNoTests=false "
    "-Dskip.installnodenpm -Dskip.npm -Dskip.yarn -Dlicense.skip -Dcheckstyle.skip "
    "-Drat.skip -Denforcer.skip -Danimal.sniffer.skip -Dmaven.javadoc.skip "
    "-Dfindbugs.skip -Dwarbucks.skip -Dmodernizer.skip -Dimpsort.skip "
    "-Dmdep.analyze.skip -Dpgpverify.skip -Dxml.skip -Dcobertura.skip=true "
    "-Dfindbugs.skip=true -Djacoco.skip=true -Dmaven.test.failure.ignore=true"
)

BUILD_TIMEOUT_S = 2400   # 40 min for the one-time project build
RUN_TIMEOUT_S = 360      # 6 min default for one test execution

# properties file surefire loads into forked JVMs; we use it for the jline
# terminal bypass (see run_mvn in junit_driver.py)
JLINE_PROPS = "/root/flakeagent/jline.properties"
GATE_RUNS = 10           # validation gate: runs per test for ground-truth repro
BASELINE_RUNS = 3        # agent's own pre-loop baseline runs
MAX_LLM_CALLS = 6
MAX_EXECUTIONS = 8
MAX_WALLCLOCK_S = 45 * 60
