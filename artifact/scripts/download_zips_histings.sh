#!/bin/bash
# Bulk-download ReproFlake zips listed in data/downloads.txt (resume + retry, 3 parallel).
# Direct connection (no proxy — zenodo is reachable directly from this network).
# Paths rewritten for the histings machine (original script hardcoded C:/Users/Paul).
# Usage: bash artifact/scripts/download_zips_histings.sh [nparallel]
set -u
cd "$(dirname "$0")/../.."   # project root (FSE_autoresearch)

ZIPDIR="$(pwd)/workdir/zips"
mkdir -p "$ZIPDIR"
NP=${1:-3}
LOG="artifact/data/downloads.log"

echo "=== [$(date +%F_%T)] download start, parallel=$NP, dir=$ZIPDIR ===" >> "$LOG"

dl() {
  line="$1"
  url="${line%%  out=*}"
  name="${line##*  out=}"
  # strip any trailing \r (Windows line endings in downloads.txt)
  name=$(printf '%s' "$name" | tr -d '\r')
  url=$(printf '%s' "$url" | tr -d '\r')
  out="$ZIPDIR/$name"
  # resume + retry; -C - resumes an existing partial file
  if curl -sS -L -C - --retry 8 --retry-delay 8 --retry-all-errors \
       --max-time 3600 -o "$out" "$url"; then
    echo "[ok] $name" >> "$LOG"
  else
    echo "[FAIL] $name (retrying once more)" >> "$LOG"
    sleep 5
    if curl -sS -L -C - --retry 8 --retry-delay 8 --retry-all-errors \
         --max-time 3600 -o "$out" "$url"; then
      echo "[ok-retry] $name" >> "$LOG"
    else
      echo "[DEAD] $name" >> "$LOG"
    fi
  fi
}
export -f dl
export ZIPDIR LOG

# download only; xargs -P gives parallel curl processes
grep -v '^#' artifact/data/downloads.txt | grep -v '^[[:space:]]*$' | \
  xargs -n1 -P"$NP" -I{} bash -c 'dl "$1"' _ {}

echo "=== [$(date +%F_%T)] download done. see $LOG ===" >> "$LOG"
echo "done. see artifact/data/downloads.log"
