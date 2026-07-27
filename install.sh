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
echo ""
read -rp "Port for the backend [default: 8000]: " PORT
PORT="${PORT:-8000}"

# --- .env file ---
ENV_FILE="$REPO_DIR/.env"

# Migrate old backend/.env if present
if [ ! -f "$ENV_FILE" ] && [ -f "$REPO_DIR/backend/.env" ]; then
  echo "Migrating backend/.env to repo root..."
  mv "$REPO_DIR/backend/.env" "$ENV_FILE"
fi

if [ ! -f "$ENV_FILE" ]; then
  SECRET_KEY=$("$BACKEND_VENV/bin/python" -c "import secrets; print(secrets.token_hex(32))")
  cat > "$ENV_FILE" <<EOF
SECRET_KEY=$SECRET_KEY
BOT_TOKEN=your-telegram-bot-token-here
ALLOWED_IDS=comma,separated,telegram,ids
PORT=$PORT
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

# --- Systemd services ---
if [ -d /etc/systemd/system ] && [ -d "$REPO_DIR/deploy" ]; then
  echo ""
  read -rp "Install systemd services? [y/N] " INSTALL_SERVICES
  if [[ "$INSTALL_SERVICES" =~ ^[Yy]$ ]]; then
    CURRENT_USER="${SUDO_USER:-$(whoami)}"
    for svc in gse-backend.service gse-bot.service gse-snapshot.service gse-snapshot.timer; do
      sed "s|/opt/gse-portfolio|$REPO_DIR|g; s|User=%i|User=$CURRENT_USER|g; s|--port 8000|--port $PORT|g" \
        "$REPO_DIR/deploy/$svc" | sudo tee "/etc/systemd/system/$svc" >/dev/null
    done
    sudo systemctl daemon-reload
    sudo systemctl enable gse-backend gse-bot gse-snapshot.timer
    if grep -q "your-telegram-bot-token-here" "$ENV_FILE" 2>/dev/null; then
      echo "Services installed but NOT started — edit $ENV_FILE first, then:"
      echo "  sudo systemctl start gse-backend gse-bot gse-snapshot.timer"
    else
      sudo systemctl restart gse-backend gse-bot
      sudo systemctl start gse-snapshot.timer
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
        Content-Security-Policy "default-src 'self'; script-src 'self' https://telegram.org https://cdnjs.cloudflare.com; frame-src https://telegram.org; style-src 'self' 'unsafe-inline'; connect-src 'self' https://telegram.org; img-src 'self' data:"
    }
}
EOF
    sudo cp /tmp/gse-Caddyfile /etc/caddy/Caddyfile
    sudo systemctl enable caddy
    sudo systemctl restart caddy
    echo "Caddy configured for $DOMAIN — HTTPS will be automatic once DNS propagates."
  fi
fi

echo ""
echo "=== Install complete ==="
echo ""
echo "Manual start:"
echo "  cd $REPO_DIR/backend && source .venv/bin/activate && source ../.env"
echo "  uvicorn main:app --host 0.0.0.0 --port $PORT"
