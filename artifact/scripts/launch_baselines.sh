#!/bin/bash
# Launch non-agent baselines + singleshot (fixed code, clean TD bytecode) detached.
cd /mnt/c/Users/histings/Desktop/FSE_autoresearch/artifact/scripts
set -a; . /root/flakeagent/keys.env; set +a
export JAVA_HOME=/opt/tools/jdk8
export PATH="$JAVA_HOME/bin:$PATH"
nohup python3 baselines.py --with-singleshot --workers 2 > /root/flakeagent/run_baselines.log 2>&1 &
sleep 5
echo 'launched baselines; pids:'
pgrep -af '[b]aselines.py'
