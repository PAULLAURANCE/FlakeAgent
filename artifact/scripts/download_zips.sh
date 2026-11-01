#!/bin/bash
# Bulk-download ReproFlake zips listed in data/downloads.txt (resume + retry, 3 parallel).
# Usage: bash artifact/scripts/download_zips.sh [nparallel]
cd "c:/Users/histings/Desktop/FSE_autoresearch"
ZIPDIR="c:/Users/histings/Desktop/FSE_autoresearch/workdir/zips"
mkdir -p "$ZIPDIR"
PROXY="http://127.0.0.1:7897"
NP=${1:-3}
LOG="artifact/data/downloads.log"

dl() {
  line="$1"
  url="${line%%  out=*}"
  name="${line##*  out=}"
  if [ -f "$ZIPDIR/$name" ]; then
    # verify size: if curl says already complete we skip via -C - (curl re-checks)
    :
  fi
  curl -sS -L -C - --retry 5 --retry-delay 8 --retry-all-errors \
       --max-time 1800 -x "$PROXY" -o "$ZIPDIR/$name" "$url" \
    && echo "[ok] $name" >> "$LOG" \
    || { echo "[FAIL] $name" >> "$LOG"; curl -sS -L -C - --retry 5 --retry-delay 8 --retry-all-errors --max-time 1800 -x "$PROXY" -o "$ZIPDIR/$name" "$url" \
      && echo "[ok-retry] $name" >> "$LOG" || echo "[DEAD] $name" >> "$LOG"; }
}
export -f dl
export ZIPDIR PROXY LOG
grep -v '^#' artifact/data/downloads.txt | xargs -n1 -P"$NP" bash -c 'dl "$1"' _
echo "done. see $LOG"
