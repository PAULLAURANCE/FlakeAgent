#!/bin/bash
# Chain the remaining compute phases after baselines finish.
# Each phase is sequential (respects the 2-worker heat cap); the whole script
# is launched detached. Waits at start for the baselines run (pid 27) to exit.
cd /mnt/c/Users/histings/Desktop/FSE_autoresearch/artifact/scripts
set -a; . /root/flakeagent/keys.env; set +a
export JAVA_HOME=/opt/tools/jdk8
export PATH="$JAVA_HOME/bin:$PATH"
LOG=/root/flakeagent/run_remaining.log

echo "=== [$(date)] waiting for baselines to finish ===" >> "$LOG"
while pgrep -f "python3 baselines.py --with-singleshot" >/dev/null; do sleep 60; done
echo "=== [$(date)] baselines done; starting ablations/models/variance ===" >> "$LOG"

# 50-test stratified subset (shared by the 3 x50 ablations + 5 models)
python3 stratify_subset.py >> "$LOG" 2>&1

# ---- Ablations (ds-flash) ----
for ab in noreflection space4 nosource warm; do
  ROWS=""
  [ "$ab" != "noreflection" ] && ROWS="--rows-file ../data/summary/model50_tests.csv"
  echo "=== [$(date)] ablation $ab ===" >> "$LOG"
  python3 run_cell.py --model ds-flash --ablation "$ab" --workers 2 $ROWS >> "$LOG" 2>&1
done

# ---- Cross-model comparison (50-test subset) ----
for m in ds-pro gemini38 grok47 sol astra; do
  echo "=== [$(date)] model $m ===" >> "$LOG"
  python3 run_cell.py --model "$m" --rows-file ../data/summary/model50_tests.csv --workers 2 >> "$LOG" 2>&1
done

# ---- Variance (30-test subset, 3 seeds) ----
# seed 0 = the main run (agent_ds-flash.jsonl, already covers the 30 tests);
# only seeds 1 and 2 are new (run_cell.py --seed 0 would APPEND to the main file).
python3 analyze.py >> "$LOG" 2>&1   # also writes variance_tests.csv (seed 42)
for s in 1 2; do
  echo "=== [$(date)] variance seed $s ===" >> "$LOG"
  python3 run_cell.py --model ds-flash --rows-file ../data/summary/variance_tests.csv --seed "$s" --workers 2 >> "$LOG" 2>&1
done
echo "=== [$(date)] variance baselines (3 seeds) ===" >> "$LOG"
python3 baselines.py --baselines naive,random,shuffle --seeds 3 \
  --rows-file ../data/summary/variance_tests.csv --workers 2 >> "$LOG" 2>&1

# ---- Final analysis ----
echo "=== [$(date)] final analyze ===" >> "$LOG"
python3 analyze.py >> "$LOG" 2>&1
echo "=== [$(date)] ALL REMAINING PHASES DONE ===" >> "$LOG"
