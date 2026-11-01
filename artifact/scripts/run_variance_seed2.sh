#!/bin/bash
# 方差 seed2 启动脚本
cd /mnt/c/Users/histings/Desktop/FSE_autoresearch/artifact/scripts
source /root/flakeagent/keys.env
export JAVA_HOME=/opt/tools/jdk8
export PATH="$JAVA_HOME/bin:$PATH"
nohup python3 run_cell.py --model ds-flash --rows-file ../data/summary/variance_tests.csv --seed 2 --workers 4 > /root/flakeagent/run_variance_s2.log 2>&1 &
echo "seed2 launched PID $!"
