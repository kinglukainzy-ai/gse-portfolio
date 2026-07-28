#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== GSE Portfolio — Install ==="
echo ""

# --- System packages (Ubuntu/Debian) ---
if command -v apt-get &>/dev/null; then
  echo "Checking system packages..."
  NEEDED=()
  for pkg in python3 python3-venv python3-pip; do
    dpkg -s "$pkg" &>/dev/null || NEEDED+=("$pkg")
  done
  if [ ${#NEEDED[@]} -gt 0 ]; then
    echo "Installing: ${NEEDED[*]}"
    sudo apt-get update -qq
    sudo apt-get install -y -qq "${NEEDED[@]}"
  fi
fi

# --- Python ---
PYTHON=""
for candidate in python3 python; do
  command -v "$candidate" &>/dev/null && PYTHON="$candidate" && break
done
[ -z "$PYTHON" ] && echo "ERROR: Python 3 not found." && exit 1

PY_VERSION=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Using $PYTHON ($PY_VERSION)"

# --- Backend venv ---
BACKEND_VENV="$REPO_DIR/backend/.venv"
[ ! -d "$BACKEND_VENV" ] && echo "Creating backend venv..." && "$PYTHON" -m venv "$BACKEND_VENV"
echo "Installing backend dependencies..."
"$BACKEND_VENV/bin/pip" install --quiet --upgrade pip
"$BACKEND_VENV/bin/pip" install --quiet -r "$REPO_DIR/backend/requirements.txt"

# --- Bot venv ---
BOT_VENV="$REPO_DIR/bot/.venv"
[ ! -d "$BOT_VENV" ] && echo "Creating bot venv..." && "$PYTHON" -m venv "$BOT_VENV"
echo "Installing bot dependencies..."
"$BOT_VENV/bin/pip" install --quiet --upgrade pip
"$BOT_VENV/bin/pip" install --quiet -r "$REPO_DIR/bot/requirements.txt"

# --- Port selection ---
port_in_use() {
  # Returns 0 (true) if something is already listening on $1
  ss -tlnH 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1\$"
}

find_free_port() {
  local p="$1"
  while port_in_use "$p"; do
    p=$((p + 1))
  done
  echo "$p"
}

echo ""
read -rp "Port for the backend [default: 8000]: " PORT
PORT="${PORT:-8000}"

if port_in_use "$PORT"; then
  SUGGESTED="$(find_free_port "$PORT")"
  echo ""
  echo "WARNING: port $PORT is already in use by another process (check 'sudo ss -tlnp | grep :$PORT')."
  read -rp "Use free port $SUGGESTED instead? [Y/n] " USE_SUGGESTED
  if [[ ! "$USE_SUGGESTED" =~ ^[Nn]$ ]]; then
    PORT="$SUGGESTED"
    echo "Using port $PORT."
  else
    echo "Keeping port $PORT — the backend will fail to bind until you free it up yourself."
  fi
fi

# --- .env file ---
ENV_FILE="$REPO_DIR/.env"

# Migrate old backend/.env if present
if [ ! -f "$ENV_FILE" ] && [ -f "$REPO_DIR/backend/.env" ]; then
  echo "Migrating backend/.env to repo root..."
  mv "$REPO_DIR/backend/.env" "$ENV_FILE"
  # Remove placeholder values that crash startup
  sed -i 's/^ALLOWED_IDS=comma,separated,telegram,ids/ALLOWED_IDS=/' "$ENV_FILE"
  sed -i 's/^BOT_TOKEN=your-telegram-bot-token-here/BOT_TOKEN=/' "$ENV_FILE"
fi

if [ ! -f "$ENV_FILE" ]; then
  SECRET_KEY=$("$BACKEND_VENV/bin/python" -c "import secrets; print(secrets.token_hex(32))")
  cat > "$ENV_FILE" <<EOF
SECRET_KEY=$SECRET_KEY
BOT_TOKEN=
ALLOWED_IDS=
PORT=$PORT
COOKIE_SECURE=false
EOF
  echo ""
  echo "Created $ENV_FILE — edit it to set BOT_TOKEN and ALLOWED_IDS."
else
  # Update PORT in existing .env
  if grep -q "^PORT=" "$ENV_FILE"; then
    sed -i "s/^PORT=.*/PORT=$PORT/" "$ENV_FILE"
  else
    echo "PORT=$PORT" >> "$ENV_FILE"
  fi
  echo ".env exists — updated PORT=$PORT."
fi

# --- Load .env ---
set -a; source "$ENV_FILE"; set +a

# --- Init database ---
echo "Initializing database..."
cd "$REPO_DIR/backend"
"$BACKEND_VENV/bin/python" -c "import db; db.init_db(); print('Database ready.')"

# --- Tests ---
echo "Running tests..."
"$BACKEND_VENV/bin/python" -m pytest tests/ -q || echo "Some tests failed — check above."

# --- Warm price cache ---
echo ""
echo "Seeding live price cache..."
cd "$REPO_DIR/backend"
"$BACKEND_VENV/bin/python" price_poller.py || echo "Price poller skipped (API unreachable)."

# --- Import historical data if available ---
HISTORY_CSV="$REPO_DIR/Daily Shares  ETFs 2023.csv"
if [ -f "$HISTORY_CSV" ]; then
  echo ""
  echo "Importing historical price data from CSV..."
  "$BACKEND_VENV/bin/python" import_history.py "$HISTORY_CSV" || echo "History import skipped (file unreadable)."
else
  echo ""
  echo "No historical CSV found at $HISTORY_CSV — skipping history import."
fi

# --- Systemd services ---
if [ -d /etc/systemd/system ] && [ -d "$REPO_DIR/deploy" ]; then
  echo ""
  read -rp "Install systemd services? [y/N] " INSTALL_SERVICES
  if [[ "$INSTALL_SERVICES" =~ ^[Yy]$ ]]; then
    CURRENT_USER="${SUDO_USER:-$(whoami)}"

    # Stop any existing units first — avoids stale ExecStart paths (e.g. from a
    # previous install run as a different user) fighting the new config, and
    # resets any crash-restart loop before we replace the unit files.
    for svc in gse-backend gse-bot gse-snapshot.timer gse-poller.timer; do
      if systemctl is-enabled "$svc" &>/dev/null || systemctl is-active "$svc" &>/dev/null; then
        sudo systemctl stop "$svc" 2>/dev/null || true
      fi
    done

    for svc in gse-backend.service gse-bot.service gse-snapshot.service gse-snapshot.timer gse-poller.service gse-poller.timer; do
      sed "s|/opt/gse-portfolio|$REPO_DIR|g; s|User=%i|User=$CURRENT_USER|g; s|--port 8000|--port $PORT|g" \
        "$REPO_DIR/deploy/$svc" | sudo tee "/etc/systemd/system/$svc" >/dev/null
    done
    sudo systemctl reset-failed gse-backend gse-bot 2>/dev/null || true
    sudo systemctl daemon-reload
    sudo systemctl enable gse-backend gse-bot gse-snapshot.timer gse-poller.timer
    if grep -q "your-telegram-bot-token-here" "$ENV_FILE" 2>/dev/null; then
      echo "Services installed but NOT started — edit $ENV_FILE first, then:"
      echo "  sudo systemctl start gse-backend gse-bot gse-snapshot.timer gse-poller.timer"
    else
      sudo systemctl restart gse-backend gse-bot
      sudo systemctl start gse-snapshot.timer gse-poller.timer
      echo "Services started."
    fi
  fi
fi

# --- Caddy ---
if ! command -v caddy &>/dev/null && command -v apt-get &>/dev/null; then
  echo ""
  read -rp "Install Caddy web server? [y/N] " INSTALL_CADDY
  if [[ "$INSTALL_CADDY" =~ ^[Yy]$ ]]; then
    sudo apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
      | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>/dev/null
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
      | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
    sudo apt-get update -qq && sudo apt-get install -y -qq caddy
    echo "Caddy installed."
  fi
fi

if command -v caddy &>/dev/null; then
  # Warn if something else already owns 80/443 — Caddy will silently fail to
  # start otherwise, and requests will keep hitting whatever's already there.
  if port_in_use 80 || port_in_use 443; then
    HOLDER=$(sudo ss -tlnp 2>/dev/null | grep -E ':80 |:443 ' | grep -oP '(?<=users:\(\(")[^"]+' | sort -u | tr '\n' ' ')
    echo ""
    echo "WARNING: port 80 and/or 443 is already in use (by: ${HOLDER:-unknown})."
    echo "Caddy will fail to start until that's freed up."
    read -rp "Stop it now so Caddy can bind? [y/N] " STOP_HOLDER
    if [[ "$STOP_HOLDER" =~ ^[Yy]$ ]] && [ -n "$HOLDER" ]; then
      for svc in $HOLDER; do
        sudo systemctl stop "$svc" 2>/dev/null && sudo systemctl disable "$svc" 2>/dev/null \
          && echo "Stopped and disabled $svc." || echo "Could not stop $svc via systemctl — stop it manually."
      done
    fi
  fi

  echo ""
  read -rp "Domain name (e.g. gsewatch.duckdns.org, or leave blank to skip): " DOMAIN
  if [ -n "$DOMAIN" ]; then
    cat > /tmp/gse-Caddyfile <<EOF
$DOMAIN {
    reverse_proxy 127.0.0.1:$PORT
    encode gzip
    header {
        X-Frame-Options "SAMEORIGIN"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "strict-origin-when-cross-origin"
        Content-Security-Policy "default-src 'self'; script-src 'self' https://telegram.org; frame-src https://telegram.org; style-src 'self' 'unsafe-inline'; connect-src 'self' https://telegram.org; img-src 'self' data:"
    }
}
EOF
    sudo cp /tmp/gse-Caddyfile /etc/caddy/Caddyfile
    sudo systemctl enable caddy
    sudo systemctl restart caddy
    sleep 1
    if systemctl is-active --quiet caddy; then
      echo "Caddy configured for $DOMAIN — HTTPS will be automatic once DNS propagates."
    else
      echo "WARNING: Caddy failed to start. Check: sudo systemctl status caddy --no-pager"
    fi
  fi
fi

echo ""
echo "=== Install complete ==="
echo ""
echo "Manual start:"
echo "  cd $REPO_DIR/backend && source .venv/bin/activate && source ../.env"
echo "  uvicorn main:app --host 0.0.0.0 --port $PORT"