#!/usr/bin/env bash
# Reinstall script: kills all running processes for this app, tears down
# systemd units, then runs install.sh from scratch.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== GSE Portfolio — Reinstall ==="
echo ""

# --- Kill stray processes started by this app ---
# Covers manual uvicorn runs, old python processes, etc.
echo "Checking for stray processes..."
# Match common entrypoints for this repo
pids=$(pgrep -af "(uvicorn main:app|python main.py|python snapshot_job.py|python price_poller.py|python bot/main.py)" 2>/dev/null || true)
if [ -n "$pids" ]; then
  echo "Found processes:"
  echo "$pids"
  echo ""
  # Extract just the PIDs and kill them
  echo "$pids" | awk '{print $1}' | xargs -r kill 2>/dev/null || true
  sleep 1
  # Force kill anything still alive
  echo "$pids" | awk '{print $1}' | xargs -r kill -9 2>/dev/null || true
  echo "Processes killed."
else
  echo "No stray processes found."
fi
echo ""

# --- Tear down systemd units ---
if [ -d /etc/systemd/system ]; then
  echo "Tearing down systemd units..."
  for svc in gse-backend.service gse-bot.service gse-snapshot.service gse-snapshot.timer gse-poller.service gse-poller.timer; do
    if [ -f "/etc/systemd/system/$svc" ]; then
      sudo systemctl stop "$svc" 2>/dev/null || true
      sudo systemctl disable "$svc" 2>/dev/null || true
      sudo rm -f "/etc/systemd/system/$svc"
      echo "  Removed $svc"
    fi
  done
  sudo systemctl reset-failed gse-backend gse-bot 2>/dev/null || true
  sudo systemctl daemon-reload
  echo "Systemd units torn down."
  echo ""
fi

# --- Re-run the install script ---
echo "Running install.sh..."
cd "$REPO_DIR"
# Pass 'y' to systemd prompt, 'y' to Caddy prompt
printf 'y\ny\n' | bash "$REPO_DIR/install.sh"

echo ""
echo "=== Reinstall complete ==="
echo ""
echo "Next steps:"
echo "  sudo systemctl status gse-backend gse-bot gse-snapshot.timer gse-poller.timer"
echo "  tail -f /var/log/syslog | grep price-poller"
