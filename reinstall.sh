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

# Preserve the existing port from .env so install.sh doesn't prompt for it
ENV_FILE="$REPO_DIR/.env"
if [ -f "$ENV_FILE" ] && grep -q "^PORT=" "$ENV_FILE"; then
  EXISTING_PORT=$(grep "^PORT=" "$ENV_FILE" | head -1 | cut -d= -f2)
  export PORT="$EXISTING_PORT"
  echo "Preserving existing PORT=$PORT from .env"
fi

# Set non-interactive defaults for the remaining prompts
export INSTALL_SERVICES="y"
export INSTALL_CADDY="n"
export STOP_HOLDER="n"
export DOMAIN=""

# Call install.sh non-interactively — it will use env vars and skip prompts
bash "$REPO_DIR/install.sh"

echo ""
echo "=== Reinstall complete ==="
echo ""
echo "Next steps:"
echo "  sudo systemctl status gse-backend gse-bot gse-snapshot.timer gse-poller.timer"
echo "  tail -f /var/log/syslog | grep price-poller"
